# GitHub Actions for Cluster API

This directory contains GitHub Actions workflows for automated deployment and management of Kubernetes clusters using Cluster API.

## Setup

### 1. Configure Repository Secrets

Add the following secrets to your GitHub repository:

```
AWS_ACCESS_KEY_ID          # AWS access key
AWS_SECRET_ACCESS_KEY      # AWS secret key
GOOGLE_APPLICATION_CREDENTIALS_JSON  # GCP service account JSON (entire content)
```

### 2. Repository Structure

```
.github/workflows/
├── setup-management-cluster.yml    # Setup Cluster API management
├── deploy-cluster.yml              # Deploy workload clusters
├── cleanup-cluster.yml             # Cleanup clusters
└── cluster-status.yml              # Monitor cluster health
```

## Workflows

### Setup Management Cluster
- **Trigger**: Manual dispatch or push to main
- **Purpose**: Initialize Cluster API management cluster
- **Duration**: ~5-10 minutes

### Deploy Workload Cluster
- **Trigger**: Manual dispatch
- **Purpose**: Create new Kubernetes clusters
- **Parameters**:
  - Cluster name
  - Cloud provider (aws/gcp)
  - Node count
  - Instance type (optional)
  - GPU enabled (boolean)

### Cleanup Cluster
- **Trigger**: Manual dispatch
- **Purpose**: Delete clusters and resources
- **Parameters**:
  - Cluster name to delete
  - Cleanup management cluster (boolean)

### Cluster Status
- **Trigger**: Manual dispatch or scheduled (every 6 hours)
- **Purpose**: Monitor cluster health and resource usage

## Usage Examples

### 1. Deploy AWS GPU Cluster
```bash
# Via GitHub UI: Actions → Deploy Workload Cluster
# Parameters:
# - cluster_name: ml-training
# - provider: aws
# - node_count: 3
# - instance_type: p3.2xlarge
# - enable_gpu: true
```

### 2. Deploy GCP Development Cluster
```bash
# Via GitHub UI: Actions → Deploy Workload Cluster
# Parameters:
# - cluster_name: dev-cluster
# - provider: gcp
# - node_count: 2
# - enable_gpu: false
```

### 3. Check Cluster Status
```bash
# Via GitHub UI: Actions → Cluster Status → Run workflow
# Or wait for scheduled run every 6 hours
```

## Artifacts

Successful cluster deployments create kubeconfig artifacts that can be downloaded from the workflow run page.

## Security Notes

- Secrets are only accessible to workflow runs
- Kubeconfigs are stored as temporary artifacts (30 days retention)
- Management cluster runs in ephemeral Kind cluster during CI
- Consider using OIDC for cloud authentication in production

## Troubleshooting

### Common Issues

1. **Management cluster not found**
   - Run "Setup Management Cluster" workflow first

2. **Cloud authentication errors**
   - Verify repository secrets are correctly configured
   - Check cloud provider permissions

3. **Cluster deployment timeout**
   - Check cloud provider quotas
   - Verify instance types are available in selected region

4. **Resource cleanup issues**
   - Manual cleanup may be required for stuck resources
   - Check cloud provider console for remaining resources

### Monitoring

- Check workflow summaries for deployment status
- Use "Cluster Status" workflow for health monitoring
- Download kubeconfig artifacts to access clusters directly
