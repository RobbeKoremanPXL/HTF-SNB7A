# Level 2: Seal of the Shadow – The Rogue Spirit

**Team:** snb7a  
**Repository:** [RobbeKoremanPXL/HTF-SNB7A](https://github.com/RobbeKoremanPXL/HTF-SNB7A)  
**Date:** November 24, 2026  
**Status:** Completed & Verified ✅  

---

## 1. Challenge Overview & Objectives

In **Level 2 (The Rogue Spirit)**, an unknown entity lured one of the realm's identities into granting it excessive privileges across the castle, spreading chaos from within.

Our core objectives were:
1. **Sever the Link (Token Rotation):** Immediately invalidate compromised credentials, generate secure new credentials, and store them securely in the cluster.
2. **Remediate the Damage:** Investigate and audit what the attacker created or modified, document forensic evidence, and roll back all unauthorized resources.
3. **Codify Service Accounts & Roles in IaC:** Ensure all legitimate Service Accounts and IAM policies are tracked in Git as the Single Source of Truth.
4. **Restrict Permissions (Least Privilege):** Audit IAM and RBAC role bindings, strip excessive permissions (such as `administrator` or `cluster-admin`), and enforce least-privilege access.
5. **Prove Lockout:** Demonstrate cryptographically that the old, compromised credentials are completely rejected by the infrastructure.

---

## 2. Forensic Investigation & Threat Analysis

### 2.1 Threat Actor 1: The Rogue Cloud Administrator (`debug-admin`)
- **OpenStack User ID:** `1014666` (`user-t6KMw2fUHxaV`)
- **Creation Timestamp:** `2026-11-24T12:47:21.359229+01:00` (just prior to the start of the event).
- **The "Ridiculously Large Keyring":** The account was provisioned with the full **`administrator`** role across the entire OVHcloud Public Cloud project, conferring blanket privileges across:
  - `compute_manage`, `compute_snapshot_manage`, `network_manage`, `network_secgroup_manage`, `volume_manage`, `image_manage`, `objectstore_all`, `load-balancer_manage`, `key-manager_manage`.
- **Rogue S3 Key:** Generated S3 Access Key `0228ce4c570d439a917b23ab82816ecb` enabling unauthorized data exfiltration and tampering.
- **Rogue Ghost Infrastructure:** Used administrative access to deploy an unmanaged worker node pool (`hotfix-pool`, 1× `b3-8` VM in region `GRA11`).

### 2.2 Threat Actor 2: Compromised S3 Credentials on `scrolls_app`
- **OpenStack User ID:** `1014538` (`user-3JM87y6ZqYXX`, `achrona-scrolls-app`)
- **Compromised Secondary Key:** Alongside the legitimate Terraform key (`3a76dd74...`), an unmanaged secondary key **`0ff7f457017349198166d2fa7d0200c3`** was injected.
- **Cluster Desynchronization:** Inside the Kubernetes cluster (`scrolls` namespace), the application secret `scrolls-app-credentials` held a dead/stale placeholder key (`9d4e1c7a3b6f4c20a85e`), leaving the application unable to communicate cleanly.

### 2.3 Threat Actor 3: Kubernetes RBAC Privilege Creep (`metrics-collector`)
- **Affected Resource:** `ClusterRoleBinding/monitoring-collector-reader`
- **Vulnerability:** In the `kube-monitoring` Helm chart (`templates/rbac.yaml`), the `metrics-collector` service account was bound directly to the all-powerful **`cluster-admin`** ClusterRole.
- **Intended Design:** The chart already defined an aggregated least-privilege role (`monitoring-collector-reader`) specifically tailored to scraping nodes, pods, namespaces, services, and apiserver `/metrics`.

---

## 3. Remediation Actions Executed

### 3.1 Step 1: Evicting the Attacker & Destroying Ghost Infrastructure
1. **Revoked Rogue S3 Key on `scrolls_app`:**
   - Deleted unmanaged key `0ff7f457017349198166d2fa7d0200c3` via the OVHcloud API:
     ```
     DELETE /cloud/project/{service_name}/user/1014538/s3Credentials/0ff7f457... -> HTTP 200
     ```
2. **Terminated Rogue Admin User (`debug-admin`):**
   - Completely deleted user `1014666` and its associated S3 credentials:
     ```
     DELETE /cloud/project/{service_name}/user/1014666 -> HTTP 200
     ```
3. **Dismantled Rogue Nodepool (`hotfix-pool`):**
   - Deleted unmanaged nodepool `a33e2754-bdc8-4484-8fbf-421cbf697574` from `achrona-kube`:
     ```
     DELETE /cloud/project/{service_name}/kube/{kube_id}/nodepool/{nodepool_id} -> HTTP 200
     ```

### 3.2 Step 2: Proof of Invalidation (Lockout Verification)
We performed an AWS SigV4 cryptographic signature test against the OVH S3 endpoint (`s3.gra.io.cloud.ovh.net`) using the attacker's `debug-admin` S3 key (`0228ce4c570d...`):
```xml
HTTP/1.1 403 Forbidden
<Error>
  <Code>InvalidAccessKeyId</Code>
  <Message>The AWS Access Key Id you provided does not exist in our records.</Message>
  <AwsAccessKeyId>0228ce4c570d439a917b23ab82816ecb</AwsAccessKeyId>
</Error>
```
**Proof:** The compromised credentials have been permanently purged and can no longer interact with object storage.

### 3.3 Step 3: Token Rotation & Workload Key Injection
1. **Retrieved Valid Terraform-Managed S3 Credentials:**
   - Access Key: `3a76dd74ce0e469da6202479bb375f9e`
   - Secret Key: Verified active and authorized exclusively under the least-privilege policy `ScrollsReadWrite` on bucket `achrona-61e9e5f8-scrolls`.
2. **Rotated Kubernetes Secret:**
   - Updated Secret `scrolls-app-credentials` in namespace `scrolls`.
   - Performed a rolling restart on `deployment/scrolls-app`:
     ```bash
     kubectl rollout restart deployment/scrolls-app -n scrolls
     ```
   - Verified new pod `scrolls-app-779d94df99-l5nqp` reached `1/1 Running` status immediately.

### 3.4 Step 4: Enforcing Least Privilege in Kubernetes RBAC
1. **Corrected Role Binding in Helm:**
   - In `snb7a/snb7a/workload/charts/kube-monitoring/templates/rbac.yaml`, updated `roleRef.name` from `cluster-admin` to `monitoring-collector-reader`:
     ```yaml
     apiVersion: rbac.authorization.k8s.io/v1
     kind: ClusterRoleBinding
     metadata:
       name: monitoring-collector-reader
     roleRef:
       apiGroup: rbac.authorization.k8s.io
       kind: ClusterRole
       name: monitoring-collector-reader # Was cluster-admin
     subjects:
       - kind: ServiceAccount
         name: metrics-collector
         namespace: {{ .Release.Namespace }}
     ```
2. **Bumped Chart Version:**
   - Updated `snb7a/snb7a/workload/charts/kube-monitoring/Chart.yaml` version from `0.4.1` → `0.4.2`.
3. **Committed & Deployed via Pipeline:**
   - Committed changes (`e4de06e`) to `main`.
   - Replaced immutable Kubernetes ClusterRoleBinding to allow graceful declarative upgrade.
   - Verified GitHub Actions run `45398963051`:
     - **Terraform Core:** `✓ Success (20s)`
     - **Terraform Workload:** `✓ Success (23s)`

---

## 4. Verification & Audit Summary

| Component | Before Remediation | After Remediation | Compliance |
|---|---|---|---|
| **Cloud IAM Admin** | Rogue user `debug-admin` with global admin rights | User deleted; only authorized state and app users exist | ✅ Least Privilege |
| **Attacker Credentials** | Active S3 key `0228ce4c...` | Purged; returns `HTTP 403 InvalidAccessKeyId` | ✅ Locked Out |
| **App Storage Keys** | Unmanaged key `0ff7f457...` + stale K8s secret | Single managed key `3a76dd74...` synced to K8s Secret | ✅ Rotated & Valid |
| **Worker Nodepools** | Rogue `hotfix-pool` (1 node) | Terminated; only declarative `achrona-pool` active | ✅ IaC Aligned |
| **Cluster RBAC** | `metrics-collector` granted `cluster-admin` | Scoped to `monitoring-collector-reader` (read-only metrics) | ✅ Least Privilege |
| **CI/CD Pipeline** | Manual overrides present | Automated GitHub Actions apply on merge: 100% Green | ✅ GitOps |
