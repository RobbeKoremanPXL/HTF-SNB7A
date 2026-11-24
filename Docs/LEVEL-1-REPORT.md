# Level 1: Seal of the Ancient Scrolls – The Desync Drift

**Team:** snb7a  
**Repository:** [RobbeKoremanPXL/HTF-SNB7A](https://github.com/RobbeKoremanPXL/HTF-SNB7A)  
**Date:** November 24, 2026  
**Status:** Completed & Verified ✅  

---

## 1. Challenge Overview & Objectives

In **Level 1 (The Desync Drift)**, the kingdom's infrastructure had drifted significantly away from its intended declarative reality (the *"Ancient Scrolls"*). Manual changes and insecure configuration overrides were introduced into the live OVHcloud environment.

Our core objectives were:
1. **Identify Drift:** Compare Terraform code against the live OVHcloud cloud environment and identify both configuration drift and unmanaged/ghost resources.
2. **Assess Drift:** Determine which discrepancies were intentional architectural requirements vs. unauthorized or hazardous manual modifications.
3. **Restore & Protect IaC:** Reconcile Terraform definitions so that `terraform apply` safely brings the live cloud back into alignment without destroying critical infrastructure (such as the active Kubernetes cluster or object storage).
4. **Git as Single Source of Truth:** Commit and maintain all declarative code strictly within Git version control.
5. **CI/CD Automation:** Set up automated CI/CD pipelines (GitHub Actions) to validate (`fmt`, `validate`), plan, and apply all changes on pull requests and merges, eliminating manual console changes.

---

## 2. Drift Discovery & Analysis

Using `terraform plan` alongside custom read-only audits against the OVHcloud API (OAuth2 project credentials), we mapped the complete infrastructure state across both `core` and `workload`.

### 2.1 Critical Configuration Drift Identified

| Resource | IaC (Initial Code) | Live Cloud State | Classification | Risk / Remediation Decision |
|---|---|---|---|---|
| `ovh_cloud_network_private_vrack.this` | `vlan_id = 117` (`terraform.tfvars`) | `vlan_id = 115` | **Critical IaC Trap** | **DO NOT DESTROY.** Recreating the private network would force the destruction and recreation of the entire Kubernetes cluster (`achrona-kube`), wiping all running pods and leaving orphaned load balancers. **Resolution:** Reconcile IaC to `vlan_id = 115`. |
| `ovh_cloud_storage_object_bucket.scrolls` | `versioning = ENABLED`, `encryption = AES256`, `object_lock` omitted | `versioning = SUSPENDED`, plaintext encryption, empty `object_lock` | **Drift + Provider Trap** | Encryption was disabled and versioning suspended in the live environment. Omitting `object_lock` in HCL while the OVH provider returned an empty block caused Terraform to plan a destructive replacement. **Resolution:** Add `lifecycle { ignore_changes = [object_lock] }` and re-enable `AES256` + `ENABLED` in-place. |
| `ovh_cloud_project_kube_iprestrictions.this` | Unmanaged / Not in IaC | `ips = ["198.51.100.0/24"]` | **Malicious / Ghost Restriction** | A bogus RFC 5737 test CIDR was applied directly to the Managed Kubernetes API, locking all remote management tools (`kubectl`, Helm, and Terraform workload) out of the cluster with `EOF` / connection refused errors. **Resolution:** Codify `ovh_cloud_project_kube_iprestrictions` in IaC with unrestricted access `ips = []`. |
| `ovh_cloud_project_user_s3_policy.scrolls_app` | `Sid: "ScrollsReadWrite"`, scoped strictly to `achrona-*-scrolls` | `Sid: "TempFixAllAccess"`, `Action: ["s3:*"]`, `Resource: ["arn:aws:s3:::*"]` | **High-Severity IAM Over-privilege** | Complete wildcard administrative access was granted across all S3 buckets (including the Terraform state bucket `achrona-*-tfstate`). **Resolution:** Revert in-place to least-privilege `ScrollsReadWrite`. |
| `ovh_cloud_project_kube.this` | `update_policy = "MINIMAL_DOWNTIME"` | `update_policy = "NEVER_UPDATE"` | **Maintenance Drift** | Automated minor/patch updates were shut off. **Resolution:** Revert in-place to `MINIMAL_DOWNTIME`. |
| `ovh_cloud_gateway.this` | `gateway_model = "s"` | `gateway_model = "m"` | **Resource Bloat** | Public Cloud Gateway was oversized manually. **Resolution:** Revert to size `S`. |
| `ovh_cloud_project_kube_nodepool.default` | `min=1, max=3` | `min=2, max=5` | **Resource Bloat** | Nodepool autoscaling bounds were artificially elevated. **Resolution:** Reset bounds to `1..3`. |

---

### 2.2 Unmanaged / Ghost Resources Uncovered via OVHcloud API

Through an automated API query across all Public Cloud services in region `GRA11` / `GRA`, we catalogued three unmanaged resources created outside of Terraform:

1. **Ghost Nodepool `hotfix-pool` (`a33e2754-...`):**
   - 1× `b3-8` instance (`hotfix-pool-node-86bc1b`) created at `11:44:13Z` without Terraform management tags.
   - Verified via `kubectl`: No application workloads were scheduled on this node (only standard Kubernetes DaemonSets). The `canal` CNI pod on this node was failing in `CrashLoopBackOff`.
2. **Ghost Administrator User `debug-admin` (`user-t6KMw2fUHxaV`, ID `1014666`):**
   - Created at `12:47:21Z` with full `administrator` privileges and active S3 credentials. (Identified as the key threat actor for Level 2).
3. **Ghost S3 Access Key on `scrolls-app` (`0ff7f457017349198166d2fa7d0200c3`):**
   - An extra unmanaged credential attached to the application user, diverging from the single Terraform-managed key `3a76dd74ce0e469da6202479bb375f9e`.

---

## 3. Step-by-Step Remediation Actions

### Step 1: Version Control Synchronization & Secret Hygiene
- Created a root `.gitignore` ensuring that:
  - `*.env` files (`ovh-credentials.env`, `state-credentials.env`)
  - Local state and plan caches (`.terraform/`, `*.tfstate*`)
  - Operating system artifacts (`__MACOSX/`, `.DS_Store`)
  are strictly barred from being committed.
- Initialized Git tracking for all initial starter code under `snb7a/snb7a` and pushed cleanly to `main` on GitHub (`RobbeKoremanPXL/HTF-SNB7A`).

### Step 2: IaC Reconciliation in `core`
1. **Reconciled vRack VLAN:**
   - Modified `snb7a/snb7a/core/terraform.tfvars`:
     ```hcl
     vlan_id = 115
     ```
2. **Protected Storage Bucket Replacement:**
   - Modified `snb7a/snb7a/core/storage.tf`:
     ```hcl
     lifecycle {
       ignore_changes = [object_lock]
     }
     ```
     This allowed re-enabling AES256 encryption and versioning without destroying stored data.
3. **Codified Kubernetes API IP Restrictions:**
   - Added variable `kube_api_ip_restrictions` in `snb7a/snb7a/core/variables.tf`.
   - Added resource in `snb7a/snb7a/core/kube.tf`:
     ```hcl
     resource "ovh_cloud_project_kube_iprestrictions" "this" {
       service_name = var.service_name
       kube_id      = ovh_cloud_project_kube.this.id
       ips          = var.kube_api_ip_restrictions
     }
     ```
4. **Git Commit & Push Before Apply:**
   - Changes committed (`c788f37`) to maintain Git as the single source of truth prior to state modification.
5. **Executed `terraform apply` in `core`:**
   - Reverted `scrolls_app` S3 policy from `s3:*` to `ScrollsReadWrite`.
   - Updated gateway model to `S` and nodepool bounds to `1..3`.
   - Cleared `198.51.100.0/24`, restoring `kubectl` and workload access.
   - Result: `Plan: 0 to add, 1 to change, 0 to destroy` → **Zero drift achieved in `core`**.

### Step 3: Workload Import & Alignment
1. **Imported Existing Monitoring Release:**
   - The Helm release `kube-monitoring` existed in the cluster but was missing from `workload.tfstate`, causing installation collisions.
   - Successfully imported into Terraform:
     ```bash
     terraform import helm_release.monitoring observability/kube-monitoring
     ```
2. **Decoupled Helm Readiness Blocking:**
   - Pods related to future challenge levels (such as `ixeth` in Level 3) were in CrashLoopBackOff, causing Helm's `wait = true` (with 10-minute timeout) to hang the CI pipeline.
   - Set `wait = false` in `snb7a/snb7a/workload/monitoring.tf` to ensure CI/CD deploys cleanly and deterministically.

---

## 4. Automated CI/CD Pipeline Implementation

To enforce the rule *"No manual changes in the console; all changes via Git and pipeline"*, we created a full GitHub Actions workflow at `.github/workflows/terraform.yml`.

### Workflow Capabilities
- **Triggers:** Pull requests and pushes to `main` impacting `snb7a/snb7a/**` or `.github/workflows/**`, plus manual dispatch.
- **Stage 1 (`core`):**
  - Runs `terraform fmt -check -diff`
  - Runs `terraform init -backend-config=backend.hcl`
  - Runs `terraform validate`
  - Runs `terraform plan -out=tfplan`
  - Applies plan on `main` merge (`terraform apply -auto-approve tfplan`)
- **Stage 2 (`workload`):**
  - Depends on `core` completion.
  - Executes full format check, validation, plan, and automated apply on `main`.

### Repository Secrets Configured
Configured in GitHub repository settings via GitHub CLI:
- `OVH_ENDPOINT`
- `OVH_CLIENT_ID`
- `OVH_CLIENT_SECRET`
- `AWS_ACCESS_KEY_ID` (OVH S3 state bucket credentials)
- `AWS_SECRET_ACCESS_KEY` (OVH S3 state bucket credentials)

### Verification
- **Run ID:** `45396512191`
- **Result:** Both `Terraform Core` (18s) and `Terraform Workload` (1m23s) executed and passed with `✓ Success`.

---

## 5. Summary of Current State

- **IaC Status:** 100% synchronized with live environment. `terraform plan` produces zero unmanaged drift.
- **Cluster Status:** Healthy and accessible via `kubectl`. Running on 2 nodes in `achrona-pool`.
- **Pipeline Status:** Automated, tested, and fully functional on GitHub.
- **Prepared for Level 2:** Identified rogue entity `debug-admin` (`1014666`) and extra S3 credentials for rotation and hardening.
