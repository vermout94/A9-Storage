import pulumi
from pulumi_azure_native import resources, compute, network, dataprotection, recoveryservices
import pulumi_command as command
import os

# Export environment variables for username and password
admin_username = os.getenv('ADMIN_USERNAME', 'azureuser')
admin_password = os.getenv('ADMIN_PASSWORD', 'P@ssw0rd1234')

# Step 1: Set up the required infrastructure
# Create a resource group
resource_group = resources.ResourceGroup('workshop_rg')

# Create a virtual network
vnet = network.VirtualNetwork(
    'vnet',
    resource_group_name=resource_group.name,
    address_space=network.AddressSpaceArgs(
        address_prefixes=["10.0.0.0/16"],
    )
)

# Create a subnet
subnet = network.Subnet(
    'subnet',
    resource_group_name=resource_group.name,
    virtual_network_name=vnet.name,
    address_prefix="10.0.1.0/24"
)

# Create Network Interfaces for VMs
nic1 = network.NetworkInterface(
    'nic1',
    resource_group_name=resource_group.name,
    ip_configurations=[network.NetworkInterfaceIPConfigurationArgs(
        name='ipconfig1',
        subnet=network.SubnetArgs(id=subnet.id),
        private_ip_allocation_method='Dynamic'
    )]
)

nic2 = network.NetworkInterface(
    'nic2',
    resource_group_name=resource_group.name,
    ip_configurations=[network.NetworkInterfaceIPConfigurationArgs(
        name='ipconfig2',
        subnet=network.SubnetArgs(id=subnet.id),
        private_ip_allocation_method='Dynamic'
    )]
)

# Create Virtual Machines
vm1 = compute.VirtualMachine(
    'vm1',
    resource_group_name=resource_group.name,
    network_profile=compute.NetworkProfileArgs(
        network_interfaces=[compute.NetworkInterfaceReferenceArgs(
            id=nic1.id,
        )],
    ),
    hardware_profile=compute.HardwareProfileArgs(
        vm_size='Standard_DS1_v2'
    ),
    os_profile=compute.OSProfileArgs(
        computer_name='vm1',
        admin_username=admin_username,
        admin_password=admin_password
    ),
    storage_profile=compute.StorageProfileArgs(
        image_reference=compute.ImageReferenceArgs(
            publisher='Canonical',
            offer='UbuntuServer',
            sku='18.04-LTS',
            version='latest'
        )
    )
)

vm2 = compute.VirtualMachine(
    'vm2',
    resource_group_name=resource_group.name,
    network_profile=compute.NetworkProfileArgs(
        network_interfaces=[compute.NetworkInterfaceReferenceArgs(
            id=nic2.id,
        )],
    ),
    hardware_profile=compute.HardwareProfileArgs(
        vm_size='Standard_DS1_v2'
    ),
    os_profile=compute.OSProfileArgs(
        computer_name='vm2',
        admin_username=admin_username,
        admin_password=admin_password
    ),
    storage_profile=compute.StorageProfileArgs(
        image_reference=compute.ImageReferenceArgs(
            publisher='Canonical',
            offer='UbuntuServer',
            sku='18.04-LTS',
            version='latest'
        )
    )
)

# Step 1.1: Install Nginx on the VMs
connection1 = command.remote.ConnectionArgs(
    host=nic1.ip_configurations[0].private_ip_address,
    user=admin_username,
    password=admin_password
)

connection2 = command.remote.ConnectionArgs(
    host=nic2.ip_configurations[0].private_ip_address,
    user=admin_username,
    password=admin_password
)

install_nginx_vm1 = command.remote.Command(
    'installNginxVm1',
    connection=connection1,
    create='sudo apt update && sudo apt install -y nginx'
)

install_nginx_vm2 = command.remote.Command(
    'installNginxVm2',
    connection=connection2,
    create='sudo apt update && sudo apt install -y nginx'
)

# Step 2: Deploy two managed disks
config = pulumi.Config()
disk_size_gb = config.get_int('diskSize') or 100

managed_disk1 = compute.Disk(
    'managedDisk1',
    resource_group_name=resource_group.name,
    disk_size_gb=disk_size_gb,
    creation_data=compute.CreationDataArgs(
        create_option='Empty',
    )
)

managed_disk2 = compute.Disk(
    'managedDisk2',
    resource_group_name=resource_group.name,
    disk_size_gb=disk_size_gb,
    creation_data=compute.CreationDataArgs(
        create_option='Empty',
    )
)

# Step 3: Attach managed disks to the virtual machines
attach_disks = config.get_bool('attachDisks') or False

if attach_disks:
    data_disk1 = compute.DataDiskArgs(
        lun=0,
        create_option='Attach',
        managed_disk=compute.ManagedDiskParametersArgs(
            id=managed_disk1.id,
        )
    )
    vm1.storage_profile.data_disks = [data_disk1]

    data_disk2 = compute.DataDiskArgs(
        lun=0,
        create_option='Attach',
        managed_disk=compute.ManagedDiskParametersArgs(
            id=managed_disk2.id,
        )
    )
    vm2.storage_profile.data_disks = [data_disk2]


# Step 4: Backup Configuration
# Create a Recovery Services Vault
backup_vault = recoveryservices.Vault(
    'backupVault',
    resource_group_name=resource_group.name,
    sku=recoveryservices.SkuArgs(
        name='Standard',
    ),
    properties=recoveryservices.VaultPropertiesArgs(
        backup_storage_redundancy='LocallyRedundant'
    )
)

# Create a Backup Policy
backup_policy = dataprotection.BackupPolicy(
    'backupPolicy',
    resource_group_name=resource_group.name,
    vault_name=backup_vault.name,
    properties=dataprotection.BackupPolicyResourceArgs(
        policy_rule_list=[
            dataprotection.AzureBackupPolicyRuleArgs(
                name="DailyBackup",
                schedule_policy=dataprotection.SimpleSchedulePolicyArgs(
                    schedule_frequency="Daily",
                    schedule_run_times=["00:00:00"]
                ),
                retention_policy=dataprotection.LongTermRetentionPolicyArgs(
                    daily_retention=dataprotection.DailyRetentionScheduleArgs(
                        retention_duration=dataprotection.RetentionDurationArgs(
                            count=30,
                            duration_type="Days"
                        )
                    )
                )
            )
        ]
    )
)

# Protect Managed Disks
disk_protection1 = dataprotection.BackupInstance(
    'diskProtection1',
    resource_group_name=resource_group.name,
    vault_name=backup_vault.name,
    properties=dataprotection.AzureDiskBackupProtectedItemArgs(
        source_data_store=dataprotection.DataStoreType.PRIMARY,
        policy_id=backup_policy.id,
        protected_item_type="AzureDisks",
        backup_management_type="AzureWorkload",
        datasource_info=dataprotection.DatasourceSetArgs(
            resource_id=managed_disk1.id,
            datasource_type="AzureDisk"
        )
    )
)

disk_protection2 = dataprotection.BackupInstance(
    'diskProtection2',
    resource_group_name=resource_group.name,
    vault_name=backup_vault.name,
    properties=dataprotection.AzureDiskBackupProtectedItemArgs(
        source_data_store=dataprotection.DataStoreType.PRIMARY,
        policy_id=backup_policy.id,
        protected_item_type="AzureDisks",
        backup_management_type="AzureWorkload",
        datasource_info=dataprotection.DatasourceSetArgs(
            resource_id=managed_disk2.id,
            datasource_type="AzureDisk"
        )
    )
)



pulumi.export('vm1_name', vm1.name)
pulumi.export('vm2_name', vm2.name)
pulumi.export('managedDisk1_id', managed_disk1.id)
pulumi.export('managedDisk2_id', managed_disk2.id)

