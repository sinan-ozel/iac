import os
from time import sleep
from exoscale.api.v2 import Client

from helpers import wait_until

ZONE = os.environ.get('EXOSCALE_ZONE', 'ch-gva-2')
CLUSTER_NAME = os.environ['CLUSTER_NAME']

# Initialize Exoscale client
exo = Client(
    os.environ.get('EXOSCALE_API_KEY', ''),
    os.environ.get('EXOSCALE_API_SECRET', ''),
    zone=ZONE
)

print(f"Looking for SKS cluster: {CLUSTER_NAME}")

# Find the cluster
clusters_response = exo.list_sks_clusters()
clusters = clusters_response.get('sks-clusters', [])
matching_clusters = [c for c in clusters if c.get('name') == f"{CLUSTER_NAME}-cluster"]

if not matching_clusters:
    print(f"No cluster found with name {CLUSTER_NAME}-cluster")
    exit(0)

cluster = matching_clusters[0]
cluster_id = cluster['id']
print(f"Found cluster: {cluster['name']} (ID: {cluster_id})")

# List all Network Load Balancers
print("Checking for Network Load Balancers...")
nlbs_response = exo.list_load_balancers()
nlbs = nlbs_response.get('load-balancers', [])

# Get cluster details to find nodepools
print("Getting cluster details...")
cluster_details = exo.get_sks_cluster(id=cluster_id)
nodepools = cluster_details.get('nodepools', [])

# Extract instance pool IDs from nodepools
instance_pool_ids = []
for nodepool in nodepools:
    # The nodepool itself contains instance pool information
    pool_id = nodepool.get('instance-pool-id') or nodepool.get('instance-pool', {}).get('id')
    if pool_id:
        instance_pool_ids.append(pool_id)
        print(f"Found nodepool '{nodepool.get('name')}' with instance pool {pool_id}")

print(f"Total instance pools: {len(instance_pool_ids)}")
print(f"Instance pool IDs to check: {instance_pool_ids}")

# Get all instances from our instance pools
print("Getting instances from instance pools...")
pool_instance_ids = []
for pool_id in instance_pool_ids:
    try:
        pool_details = exo.get_instance_pool(id=pool_id)
        instances = pool_details.get('instances', [])
        for instance in instances:
            instance_id = instance.get('id')
            if instance_id:
                pool_instance_ids.append(instance_id)
                print(f"  Instance pool {pool_id} contains instance {instance_id}")
    except Exception as e:
        print(f"  Error getting instance pool {pool_id} details: {e}")

print(f"Total instances in pools: {len(pool_instance_ids)}")
print(f"Total NLBs to check: {len(nlbs)}")

# Find and delete NLBs that reference these instance pools
deleted_nlb_ids = []
for nlb in nlbs:
    nlb_id = nlb['id']
    nlb_name = nlb.get('name', nlb_id)

    print(f"\nChecking NLB: {nlb_name} (ID: {nlb_id})")

    # Check if this NLB has services targeting our instance pools
    try:
        nlb_details = exo.get_load_balancer(id=nlb_id)

        # Debug: Print full NLB details
        print(f"  Full NLB details: {nlb_details}")

        services = nlb_details.get('services', [])
        print(f"  NLB has {len(services)} service(s)")

        # Check for healthcheck with instance pool reference
        healthcheck = nlb_details.get('healthcheck', {})
        if healthcheck:
            print(f"  Healthcheck details: {healthcheck}")

        # Check if any service targets our instance pools or instances
        should_delete = False

        # Heuristic: Kubernetes-created NLBs have k8s- prefix
        # If the NLB was created by Kubernetes for this cluster, delete it
        if nlb_name.startswith('k8s-'):
            print(f"  ✓ NLB has k8s- prefix, likely created by Kubernetes")
            should_delete = True

        # Also check the detailed matching logic
        for service in services:
            print(f"  Service: {service.get('name', 'unnamed')}")

            # Check target pool (direct instance pool reference)
            target_pool = service.get('target-pool')
            print(f"    Target pool type: {type(target_pool)}, value: {target_pool}")
            if target_pool:
                # Handle single target pool
                if isinstance(target_pool, dict):
                    pool_id = target_pool.get('id')
                    print(f"    Checking dict target pool ID: {pool_id}")
                    if pool_id in instance_pool_ids:
                        should_delete = True
                        print(f"  ✓ MATCH! NLB {nlb_name} (ID: {nlb_id}) is attached to instance pool {pool_id}")
                        break
                # Handle list of target pools
                elif isinstance(target_pool, list):
                    for tp in target_pool:
                        pool_id = tp.get('id')
                        print(f"    Checking list target pool ID: {pool_id}")
                        if pool_id in instance_pool_ids:
                            should_delete = True
                            print(f"  ✓ MATCH! NLB {nlb_name} (ID: {nlb_id}) is attached to instance pool {pool_id}")
                            break

            # Check individual targets (Kubernetes-created NLBs use this)
            targets = service.get('target', [])
            if not isinstance(targets, list):
                targets = [targets] if targets else []

            print(f"    Service has {len(targets)} target(s)")
            for target in targets:
                if target:
                    target_instance_id = target.get('instance', {}).get('id') if isinstance(target.get('instance'), dict) else None
                    print(f"      Target instance ID: {target_instance_id}")
                    if target_instance_id and target_instance_id in pool_instance_ids:
                        should_delete = True
                        print(f"  ✓ MATCH! NLB {nlb_name} (ID: {nlb_id}) targets instance {target_instance_id} from our pool")
                        break

            if should_delete:
                break

        if should_delete:
            print(f"Deleting Network Load Balancer: {nlb_name} (ID: {nlb_id})")
            try:
                exo.delete_load_balancer(id=nlb_id)
                deleted_nlb_ids.append(nlb_id)
                print(f"Deleted NLB {nlb_name}")
            except Exception as e:
                print(f"Error deleting NLB {nlb_name}: {e}")

    except Exception as e:
        print(f"Error processing NLB {nlb_name}: {e}")# Wait for NLBs to be fully deleted
if deleted_nlb_ids:
    print(f"Waiting for {len(deleted_nlb_ids)} Network Load Balancer(s) to be deleted...")

    def check_nlbs_deleted():
        remaining_nlbs_response = exo.list_load_balancers()
        remaining_nlbs = remaining_nlbs_response.get('load-balancers', [])
        remaining_ids = [nlb['id'] for nlb in remaining_nlbs]

        still_present = [nlb_id for nlb_id in deleted_nlb_ids if nlb_id in remaining_ids]

        if still_present:
            print(f"Still waiting for {len(still_present)} NLB(s) to be deleted...")
            return False
        return True

    wait_until(
        check=check_nlbs_deleted,
        kwargs={},
        cond=lambda result: result,
        timeout=300,  # 5 minutes
        wait_interval=10
    )

    print("All Network Load Balancers deleted successfully")
else:
    print("No Network Load Balancers found to delete")

print("Load balancer teardown complete")
