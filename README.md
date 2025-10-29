# 🏗️ Infrastructure-as-Code on GitHub

This repo provisions and tears down a Kubernetes cluster on AWS and Exoscale using GitHub actions. The plan is to extend it to other providers.

I wrote this repo to achieve cloud independence and IaC automation.

## Design Principles

It is based on the following principles:
⚡ If the enviroment goes away completely, it should not take more than minutes to recover from catasrophic failure.

🎯 Production, development, and staging environment should be created using the same script to ensure compatibility.

🔄 The scripts should be as declarative as possible to allowe for readability, but should be orchestrated through an imperative scirpt.

🧹 Everything should be cleaned up during teardown.

☁️ 🪽 Cloud independence: get to Kubernetes first so that everything can be installed through Helm charts and `kubectl`.

## Overview

* Roles and users are created through local scripts (see an example [here](local_scripts/aws/eks_admin_role/)) and VS Code tasks (Just run ''Run Tasks'' and choose ''Create EKS admin role'' to see.). This is intentional, we are not letting this to be done through GitHub.
* Most of the infrastructure is declared through Pulumi (see here for an [AWS example](pulumi/aws/__main__.py)), configured through `.env` files (see [here](configs/aws/hello-k8s-ca-central-1.env) for an example) and orchestrated through [GitHub actions](.github/workflows/cluster.yaml).
* Some things have to be done through custom scripts, and these need to repeated for different providers. For instance, I want to take a snapshot before teardown on volumes, and I want to bring it back up from the snashot. These scripts are in the [`scripts/`](scripts/) folder, structured as `scripts/<provider>/<infrastructure>`


## ✨ Features

* 🚀 **One-Click Deployment** - Deploy entire Kubernetes clusters with a single GitHub Actions workflow
* ⚡ **Lightning Fast Recovery** - Recover from catastrophic failures in hours, not days
* 🔄 **Declarative Infrastructure** - Configuration using Pulumi for reproducible deployments
* 🌍 **Multi-Provider Ready** - Built to extend beyond AWS and Exoscale to other cloud providers
* 📦 **Per-Project Isolation** - Create dedicated clusters for each project with isolated resources
* 🎯 **Environment Flexibility** - Deploy dev, test, and production environments with simple config changes
* 💾 **Persistent Storage Management** - Automated provisioning of volumes
* 🔐 **Security-First** - IAM roles and policies configured with least-privilege principles
* 💰 **Cost Optimized** - Tear down resources completely when not needed to minimize cloud costs
* 🛠️ **Developer Friendly** - Simple configuration files, no complex scripting required
* ⚖️ **Hybrid Approach** - Best of both worlds: declarative configuration for visibility, imperative scripts for complex workflows
* 🚫 **Zero Installation** - No local tools required beyond GitHub Actions - everything runs in the cloud (Exception is the IAM roles creation scripts for AWS, these require VS Code and Docker. But you can also create the roles manually or just run them as Python scripts.)
* 📋 **Automated Status Report** - Automatic infrastructure health checks generate [STATUS.md] reports in your repo
* 🔍 **Configuration Checks** - GitHub Actions automatically check for duplicate configurations on commits to main

## Providers & Supported Infrastructure
| | Block Storage | Bucket Storage | Kubernetes Clusters |
|:-|:-:|:-:|:-:|
|AWS| ✅   | 🤔 | ✅  |
|Exoscale| 🗓️ | 🤔 | ✅  |
|GCP| 🤔 | 🤔 | 🤔 |
|Azure| 🤔 | 🤔 | 🤔 |

✅: Done
🗓️: Planned
🤔: Maybe

##  Why?

* Provision and tear down infrastructure for personal projects -- I don't want to forget my infrastructure and have it cost money.
  * For example, I will start using this to provision and tear down my own JupyterLab instance using GPU instances.
  * I can also use it to create data streaming projects with a full environment including Redis
  * I can use it to test new services or frameworks. I can then tear it down completely by removeing the Kubernetes cluster.
* Learning: find a professional pattern to keep environments scalable.





# 📋 Requirements

1. GitHub

# 💡 Knowledge Required to Use

1. A general understanding of DevOps
2. A general understanding of the cloud provider (AWS, and Exoscale), or whatever cloud provider you might want to add to the repo. (I find AWS particularly complex, especially with roles and policies. Make sure all IAM setup is complete.)
4. Knowledge of GitHub Actions.
5. Some knowledge of Pulumi, although I find it well-dcoumented and easier to understand compared to Terraform and to Crossplane.

You can start by cloning the repo, entering AWS secrets, creating the required role, and seeing if provisioning a cluster works. You can adjust your scripts or the configuration to your needs.


# 🚀 Getting Started

1. 📂 Clone the repo. Create a `PULUMI_PASSPHRASE` on your repo. Make sure that your repo is private.
2. 🔑 Set up the secrets, based on your provider (currently AWS and Exoscale)
3. 👤 (For AWS) Set up the required user -- see below.
3. ⚙️ Change the configuration files under `configs/` based on your need.
4. ▶️ Go to GitHub actions. Go into the `CLuster` workflow, then choose the desired configuration file and run `provision`. (Or use the `Volume` workflow to create a new volume or use a snapshot.)
5. Download the artifact, and use the entry in `kubeconfig` to run `kubectl` from your local. (Also see the [actions flow in this repo](https://github.com/sinan-ozel/jupyterlab-on-kubernetes/tree/main/.github/workflows) for a fully-automated example which downlaod the artifact and applies kubectl.)


`Volume` is for persistent block storages. It uses only Python scripts to backup, restore or create new volumes. I am using this functionality to save and recover notebooks.

`Cluster` is for provisioning the Kubernetes cluster. I plan to create multiple reusable clusters for various purposes, such as different Jupyter notebooks environments with tools attached, specific environments for streaming data testing, and at least one environment for personal servers.

## ☁️ AWS
Set up the following secrets in the repo:
🔑 `AWS_ACCESS_KEY_ID`
🆔 `AWS_ACCOUNT_ID`
🔐 `AWS_SECRET_ACCESS_KEY`

Set up the role `github-actions-iac` on AWS with the following Amazon-managed policies:
* `AmazonEBSCSIDriverPolicy`
* `AmazonEC2FullAccess`
* `AmazonEKSClusterPolicy`
* `AmazonEKSLoadBalancingPolicy`
* `AmazonEKSNetworkingPolicy`
* `AmazonEKSServicePolicy`
* `AmazonEKSWorkerNodePolicy`
* `AutoScalingFullAccess`

And also attash two "inline policies" - I also replace the asterisk in `::*:` with my 12-digit acccount id.
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PulumiCreateClusterRole",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:GetRole",
                "iam:DeleteRole",
                "iam:PutRolePolicy",
                "iam:AttachRolePolicy",
                "iam:DetachRolePolicy",
                "iam:TagRole"
            ],
            "Resource": [
                "arn:aws:iam::*:role/*-eksRole-role*",
                "arn:aws:iam::*:policy/*-eks-policy"
            ]
        },
        {
            "Sid": "PulumiReadNodeRoles",
            "Effect": "Allow",
            "Action": [
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListRoles",
                "iam:ListRolePolicies",
                "iam:ListInstanceProfiles",
                "iam:ListInstanceProfilesForRole",
                "iam:GetInstanceProfile",
                "iam:ListInstanceProfileTags",
                "iam:PassRole"
            ],
            "Resource": [
                "arn:aws:iam::*:role/*-eksRole-role*",
                "arn:aws:iam::*:role/*-node-role*",
                "arn:aws:iam::*:policy/*",
                "arn:aws:iam::*:instance-profile/*-node-instance-profile*"
            ]
        }
        {
            "Sid": "PulumiPassNodeRoles",
            "Effect": "Allow",
            "Action": [
                "iam:PassRole"
            ],
            "Resource": [
                "*"
            ],
            "Condition": {
                "StringEquals": {
                    "iam:PassedToService": [
                        "eks.amazonaws.com",
                        "ec2.amazonaws.com"
                    ]
                }
            }
        },
        {
            "Sid": "PulumiInstances",
            "Effect": "Allow",
            "Action": [
                "ec2:AssociateIamInstanceProfile",
                "ec2:DisassociateIamInstanceProfile",
                "ec2:DescribeIamInstanceProfileAssociations",
                "ec2:ReplaceIamInstanceProfileAssociation"
            ],
            "Resource": [
                "*"
            ]
        }
    ]
}```

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "eks:CreateCluster",
                "eks:ListClusters",
                "eks:DeleteCluster",
                "eks:CreateNodegroup",
                "eks:ListNodegroups",
                "eks:DescribeNodegroup",
                "eks:DeleteNodegroup",
                "eks:TagResource",
                "eks:DescribeAddon",
                "eks:DescribeAddonVersions",
                "eks:ListAddons",
                "eks:CreateAddon",
                "eks:UpdateAddon",
                "eks:DeleteAddon",
                "eks:CreateAccessEntry",
                "eks:DeleteAccessEntry",
                "eks:DescribeAccessEntry",
                "eks:ListAccessEntries",
                "eks:AssociateAccessPolicy",
                "eks:DisassociateAccessPolicy",
                "eks:ListAssociatedAccessPolicies",
                "eks:UpdateClusterConfig",
                "ssm:GetParameter"
            ],
            "Resource": "*"
        }
    ]
}
```

And the Trust Policy for the Role needs to be:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::*:oidc-provider/token.actions.githubusercontent.com"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": "repo:sinan-ozel/iac:*"
                }
            }
        }
    ]
}
```
Note that the repo here needs to be switched to yours, i.e. replace `repo:sinan-ozel/iac:*` with yours.
I also replace the asterisk in `::*:` with my own AWC account id.

Also set up a role called `kubernetes-node-role` - this is hardcoded in Pulumi
code, so if you want to change it, you also need to change the Pulumi code.
Make sure to create this on the console as an EC2 Role (When creating a new role on the console,
Choose ``AWS service'' under ``Choose trusted entity'', choose EC2 under ``Use case''.)
This automatically creates an ``instange profile'' that wraps the created role,
and this is used in the Pulumi code.

Add the following Amazon-managed policies:
* `AmazonEC2ContainerRegistryReadOnly`
* `AmazonEKS_CNI_Policy`
* `AmazonEKSWorkerNodePolicy`

## Exoscale

Set up the following secrets in the repo:
* `EXOSCALE_API_KEY`
* `EXOSCALE_API_SECRET`

# 🏗️ Structure

* `pulumi/*/` holds all the Pulumi configuration for a standard cluster. `*` here is the cloud provider. Right now I only have `aws` and `exoscale`, I might add `azure` and `gcp` in the future.
* `configs/*/` have all of the different configurations of each project. I think of these as `dev`, `staging`, but they can also be different centres serving different geographic regions in professional environments.
* `scripts/*/cluster` and `scripts/*/volume`: this is where the scripts completely custom to the provider live. The idea is to use Pulumi as much as possible, and then fall back to these scripts whenever necessary. This is because Pulumi is much easier to read. In general, the folder structure is `scripts/<provider>/<infrastructure>`.


# Known Issues
None, at the moment.

# Development

When adding a new provider or a new service, default to using Pulumi whenever possible. This makes the code mostly declarative.

When not possible, add or modify a custom script under `scripts/`. You will see that the scripts are organized in the folder structure `scripts/<provider>/<infrastructure>`.

## How to add a new provider

TODO

## How to add a new service

TODO

# TODO: Clean-up

Update:
* `.github/workflows/public.yaml`, to include `.pulumi-state`

Rename:
* Put the Pulumi code in a folder called `cluster` to keep it consistent. Update the section "Structure"
