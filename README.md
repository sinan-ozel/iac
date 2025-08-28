# 🏗️ Infrastructure-as-Code on GitHub

This repo provisions and tears down up a Kubernetes cluster on AWS using GitHub actions. The plan is to extend it to other providers.

It is based on the following philosophy:
> 💡 If the enviroment goes away completely, it should not take more than a few hours to recover from catasrophic failure.

The provisionining happens through a mixture of Python scripts, Crossplane manifests, environment files. They are all orchestrated through a GitHub Actions workflow.

## ✨ Features

🚀 **One-Click Deployment** - Deploy entire Kubernetes clusters with a single GitHub Actions workflow
⚡ **Lightning Fast Recovery** - Recover from catastrophic failures in hours, not days
🔄 **Declarative Infrastructure** - YAML-based configuration using Crossplane for reproducible deployments
🌍 **Multi-Provider Ready** - Built to extend beyond AWS to other cloud providers
📦 **Per-Project Isolation** - Create dedicated clusters for each project with isolated resources
🎯 **Environment Flexibility** - Deploy dev, test, and production environments with simple config changes
💾 **Persistent Storage Management** - Automated provisioning of volumes and buckets
🔐 **Security-First** - IAM roles and policies configured with least-privilege principles (OK, there is room for improvement in this regard... It's still a good place to start, though)
📊 **Cost Optimized** - Tear down resources completely when not needed to minimize cloud costs
🛠️ **Developer Friendly** - Simple configuration files, no complex scripting required
⚖️ **Hybrid Approach** - Best of both worlds: declarative configuration for visibility, imperative scripts for complex workflows
🚫 **Zero Installation** - No local tools required beyond GitHub Actions - everything runs in the cloud
📋 **Automated Status Report** - Automatic infrastructure health checks generate [STATUS.md] reports in your repo
🔍 **Configuration Validation** - GitHub Actions automatically check for duplicate configurations on commits to main



## Philosophy
With only imperarive scripts, it is difficult to read configuration. With only declarative g, it is challenging to provision different pieces of infrastructure in order, sometimes slowing down the process. It is also sometimes just easier to provision something in a particular manner through script: for example, I am always making a backup of a block storage before deployment and reading from the latest backup if it exists. This is really useful for personal projects, or in general, projects where you want to keep frozen for a long time without incurring a cost. This is not that easy with purely declarative solutions.

This repo intends to get the best of both worlds: declarative % imperative.
1. Use an imperative tool (Python scripts) when configuration is not that critical, or there is a specific need.
2. Use a declarative tool (Crossplane) when configuration needs to be visible.
3. Use an imperative tool (GitHub Actions) to orchestrate provisioning in order and waiting.


## 🤔 Why?

Starting the project, I had six goals in mind:
1. 🎮 Deploy and properly clean-up an environment for hobby projects (for example, I use a Jupyter notebook with high GPU memory, and I want to bring it up, use it for a few hours, and completely tear it down while backing up the notebooks. I find that Sagemaker creates tools without me realizing and keeps them up long after the notebook is gone.)
2. 📈 Make it scalable so that it can be used in some professional environments as well: Through the configuration in `manifests/*/perproject`, I can create a cluster per project. Through the configuration in `configs/*/*.env`, I can create multiple clusters in - say - different regions, or with different names (`-dev`, `-test`, etc...)
3. 📋 Provision using a declaractive solution rather than an imperative script as much as possible, so that I can change things later, and scale into multiple projects easily. It also makes it much easier to read.
4. 🏢 In a professional scenario, creating a new infrastucture should take minutes and should be reliable. This sort of approach makes this possible.
5. 🔄 Fast and successful development relies on being able to generate replicas of a production environment without much effort. This repo makes that possible. (Just write the configurations in `manifests/*/perproject/` and then substitute values using environmental variables in `configs/*/`. See the section Structure for more information.)
6. 💰 Keep personal projects in stasis for a long period of time. (For instance, I want to create notebooks that use expensive GPU instances, but then save them up automatically keep them tucked away without paying for the instances.)

### Why not Terraform?
You can actually apply the same philosophy and get this to use Terraform, rather than Crossplane. I like Crossplane because of the Kubernetes habit, and also because it accepts YAML files.

Note that this is not the best use of Crossplane. It really shines when you have a continuing control plane. Since it is built on Kubernetes, it will keep reconciling the infrastructure if something is missing. In my case, the control plane is ephemeral and disappears after provioning. However, I needed a declarative tool, and wound up choosing Crossplane, even if I am not making full use of its capabilities.


# 📋 Requirements

1. GitHub

# Knowledge Required to Use

1. A general understanding of DevOps
2. A general understanding of the cloud provider (currently only AWS), or whatever cloud provider you might want to add to the repo.
3. A general understanding of the components that are required for a Kubernetes cluster, such the VPC and the routing tables.
4. Knowledge of GitHub Actions
5. Knowledge of Crossplane configurations (YAML files)
6. Knowledge of boto3 and Python scripts, for specific provisioning scripts, and the teardown script.

You can start by cloning the repo, entering AWS secrets, creating the required role, and seeing if provisioning a cluster works. You can adjust your scripts or the configuration to your needs.


# 🚀 Getting Started

1. 📂 Clone the repo.
2. 🔑 Set up the secrets, based on your provider (currently only AWS)
3. 👤 Set up the required user in AWS.
3. ⚙️ Change the configuration files under `configs/aws` based on your need.
4. ▶️ Go to GitHub actions. Go into the `02. CLusters` workflow, then choose the desired configuration file and run `provision`.


`01. Volume` is for persistent block storages. It uses only Python scripts to backup, restore or create new volumes. I am using this functionality to save and recover notebooks.
`01. Bucket` is for buckets, but is still in development - I may come back to this only if I test HDFS.
`02. Cluster` is for provisioning the Kubernetes cluster. I plan to create multiple reusable clusters for various purposes, such as different Jupyter notebooks environments with tools attached, specific environments for streaming data testing, and at least one environment for personal servers.

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

And also attash two "inline policies" - replace the `...` with your 12-digit acccount id.
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowCreateNamedClusterRoles",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:GetRole",
                "iam:PutRolePolicy",
                "iam:AttachRolePolicy",
                "iam:TagRole"
            ],
            "Resource": [
                "arn:aws:iam::*:role/*-eks-role",
                "arn:aws:iam::*:role/*-node-role",
                "arn:aws:iam::*:policy/*-eks-policy",
                "arn:aws:iam::*:policy/*-node-policy"
            ]
        },
        {
            "Sid": "AllowPassNamedClusterRoles",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": [
                "arn:aws:iam::*:role/*-eks-role",
                "arn:aws:iam::*:role/*-node-role",
                "arn:aws:iam::*:policy/*-eks-policy",
                "arn:aws:iam::*:policy/*-node-policy"
            ],
            "Condition": {
                "StringEquals": {
                    "iam:PassedToService": "eks.amazonaws.com"
                }
            }
        }
    ]
}
```

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "eks:ListClusters",
                "eks:DeleteCluster",
                "eks:ListNodegroups",
                "eks:DescribeNodegroup",
                "eks:DeleteNodegroup"
            ],
            "Resource": "*"
        }
    ]
}
```

# 🏗️ Structure

`manifests/*/common` holds all the Crossplane configuration common to all projects.
`*` here is the cloud provider. Right now I only have `aws`, the plan is to imclude a second one soon.
`manifests/*/perproject` holds all of the Crossplane configuration specific to a project. For example, the project can be "such-an-such microservice" or something bigger like a full SaaS product. The point is that it is deployed on a cluster.
`configs/*/` have all of the different configurations of each project. I think of these as `dev`, `staging`, but they can also be different centres serving different geographic regions in professional environments.
