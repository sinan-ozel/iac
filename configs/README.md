# Configuration Files

This directory contains environment configuration files for provisioning infrastructure across cloud providers.

## Structure

Each `.env` file defines configuration for a specific project/cluster and can work across multiple providers.

**Naming Convention**: Provider-specific variables are prefixed with the provider name (`AWS_*`, `EXOSCALE_*`). All other variables are shared across providers.

### Variables

- `AWS_REGION` - AWS region (required for AWS deployments)
- `EXOSCALE_ZONE` - Exoscale zone (required for Exoscale deployments)
- `CLUSTER_NAME` - Unique cluster identifier (must be globally unique)
- `VOLUME_NAME` - Persistent volume identifier
- `PROJECT_NAME` / `PROJECT_NAMES` - Project identifier(s), comma-delimited for multiple projects
- `DEFAULT_NODE_COUNT` - Number of standard nodes
- `GPU_NODE_COUNT` - Number of GPU nodes (optional)
- `GPU_EPHEMERAL_VOLUME_SIZE` - Ephemeral storage size for GPU nodes in GB (optional)
- `ADMIN_REPOS` - Comma-delimited GitHub repo paths (e.g., `sinan-ozel/jupyterlab-on-kubernetes`) for kubectl integration on AWS

## Usage

Configs are selected via GitHub Actions workflows:
- **01. Volumes**: `provision-volume.yaml`, `teardown-volume.yaml` - Storage tier (bottom tier)
- **02. Clusters**: `provision-cluster.yaml`, `teardown-cluster.yaml`, `test-cluster.yaml` - Cluster tier including VPCs and networking

The workflow numbering reflects dependency order: storage (`01.`) must exist before clusters (`02.`).

The `provider` input determines which cloud to use (aws/exoscale), while the config file provides the parameters.

## Node Philosophy

This setup is **opinionated** about standardization:
- **One GPU node type** for GPU-intensive workloads (with taint to prevent non-GPU pods)
- **One standard node type** for memory/CPU-intensive workloads
- All projects share these node types using Kubernetes taints and tolerations

GPU nodes are tainted to ensure only GPU workloads schedule on them, maximizing resource efficiency across all clusters.

## Requirements

- `CLUSTER_NAME` must be unique across all configs
- AWS configs must define `AWS_REGION`
- Exoscale configs must define `EXOSCALE_ZONE`
- Configs can define both regions for multi-cloud flexibility
