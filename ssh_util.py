"""
SSH utility for uploading translation files to OnWatch device.
"""
import subprocess
import os
import logging
import time
import paramiko
from io import StringIO

logger = logging.getLogger(__name__)


class SSHUtil:
    """Utility for SSH/SCP operations."""
    
    def __init__(self, ip_address, username, password=None, ssh_key_path=None):
        """
        Initialize SSH utility.
        
        Args:
            ip_address: Device IP address
            username: SSH username
            password: SSH password (optional, if using SSH keys)
            ssh_key_path: Path to SSH private key (optional)
        """
        self.ip_address = ip_address
        self.username = username
        self.password = password
        self.ssh_key_path = ssh_key_path
    
    def scp_file(self, local_path, remote_path):
        """
        Copy file to remote device via SCP.
        
        Args:
            local_path: Local file path
            remote_path: Remote file path (e.g., /tmp/filename.json)
        
        Returns:
            True if successful, False otherwise
        """
        if not os.path.exists(local_path):
            logger.error(f"Local file not found: {local_path}")
            return False
        
        logger.info(f"Copying {local_path} to {self.username}@{self.ip_address}:{remote_path}")
        
        # Build SCP command
        scp_cmd = ['scp']
        
        # Add SSH key if provided
        if self.ssh_key_path and os.path.exists(self.ssh_key_path):
            scp_cmd.extend(['-i', self.ssh_key_path])
        
        # Disable host key checking (for automation)
        scp_cmd.extend(['-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null'])
        
        # Add source and destination
        scp_cmd.append(local_path)
        scp_cmd.append(f"{self.username}@{self.ip_address}:{remote_path}")
        
        try:
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"✓ Successfully copied file to {remote_path}")
                return True
            else:
                logger.error(f"SCP failed: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("SCP operation timed out")
            return False
        except Exception as e:
            logger.error(f"SCP error: {e}")
            return False
    
    def run_ssh_command(self, command, use_sudo=False, password=None):
        """
        Run command on remote device via SSH.
        
        Args:
            command: Command to run
            use_sudo: Whether to run with sudo (will prompt for password)
            password: Password for sudo (if use_sudo=True)
        
        Returns:
            Tuple of (success: bool, output: str, error: str)
        """
        logger.info(f"Running SSH command: {command}")
        
        # Build SSH command
        ssh_cmd = ['ssh']
        
        # Add SSH key if provided
        if self.ssh_key_path and os.path.exists(self.ssh_key_path):
            ssh_cmd.extend(['-i', self.ssh_key_path])
        
        # Disable host key checking
        ssh_cmd.extend(['-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null'])
        
        # Build remote command
        if use_sudo:
            if password:
                # Use sudo with password via stdin
                remote_cmd = f"echo '{password}' | sudo -S {command}"
            else:
                # Assume passwordless sudo or SSH key with sudo
                remote_cmd = f"sudo {command}"
        else:
            remote_cmd = command
        
        ssh_cmd.append(f"{self.username}@{self.ip_address}")
        ssh_cmd.append(remote_cmd)
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info(f"✓ Command executed successfully")
                return True, result.stdout, result.stderr
            else:
                logger.error(f"SSH command failed: {result.stderr}")
                return False, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            logger.error("SSH command timed out")
            return False, "", "Command timed out"
        except Exception as e:
            logger.error(f"SSH error: {e}")
            return False, "", str(e)
    
    def upload_translation_file(self, local_file_path, translation_util_path, sudo_password=None):
        """
        Upload translation file to device via SSH/SCP.
        
        This method:
        1. SCPs the file to /tmp/ on the device
        2. SSHs to device and runs translation-util upload interactively
        3. Provides the file path when prompted by the script
        
        Args:
            local_file_path: Local path to translation file
            translation_util_path: Path to translation-util script on device
            sudo_password: Password for sudo (if needed)
        
        Returns:
            True if successful, False otherwise
        """
        filename = os.path.basename(local_file_path)
        remote_tmp_path = f"/tmp/{filename}"
        
        # Step 1: SCP file to /tmp/
        logger.info(f"Step 1: Copying translation file to /tmp/ on device...")
        if not self.scp_file(local_file_path, remote_tmp_path):
            logger.error("Failed to copy file to device")
            return False
        
        # Step 2: Run translation-util upload interactively
        logger.info(f"Step 2: Running translation-util upload...")
        
        try:
            # Use paramiko for better interactive session handling
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect to SSH
            if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                # Use SSH key
                ssh.connect(
                    self.ip_address,
                    username=self.username,
                    key_filename=self.ssh_key_path,
                    timeout=30
                )
            else:
                # Use password
                if not self.password:
                    raise ValueError(
                        "SSH password is required but not provided. "
                        "Please set ssh.password in config.yaml or provide it when prompted."
                    )
                
                ssh.connect(
                    self.ip_address,
                    username=self.username,
                    password=self.password,
                    timeout=30
                )
            
            # Get script directory and name
            script_dir = os.path.dirname(translation_util_path)
            script_name = os.path.basename(translation_util_path)
            
            # Create interactive shell session
            shell = ssh.invoke_shell()
            shell.settimeout(30)
            
            # Wait for shell prompt
            time.sleep(1)
            shell.recv(1024)
            
            # Change to script directory
            logger.info(f"Changing to directory: {script_dir}")
            shell.send(f"cd {script_dir}\n")
            time.sleep(1)
            shell.recv(1024)
            
            # Run translation-util upload with sudo
            # First, if password is needed for sudo, provide it
            if sudo_password:
                logger.info("Providing sudo password...")
                shell.send(f"sudo {script_name} upload\n")
                time.sleep(1)
                # Check if sudo password prompt appears
                output = shell.recv(4096).decode('utf-8', errors='ignore')
                if "password" in output.lower() or "[sudo]" in output:
                    shell.send(f"{sudo_password}\n")
                    time.sleep(1)
            else:
                logger.info(f"Running {script_name} upload (assuming passwordless sudo)...")
                shell.send(f"sudo {script_name} upload\n")
            
            time.sleep(2)
            
            # Read output (should show available files and prompt)
            output = shell.recv(4096).decode('utf-8', errors='ignore')
            logger.info(f"Script output:\n{output}")
            
            # Check if we see the prompt for file input
            if "Please Enter Translation File To Upload" in output or "Enter" in output:
                # Provide the file path when prompted
                logger.info(f"Providing file path: {remote_tmp_path}")
                shell.send(f"{remote_tmp_path}\n")
                time.sleep(3)  # Wait for processing
            else:
                # Try providing the path anyway (script might accept it directly)
                logger.info(f"Providing file path: {remote_tmp_path}")
                shell.send(f"{remote_tmp_path}\n")
                time.sleep(3)
            
            # Read final output
            final_output = shell.recv(4096).decode('utf-8', errors='ignore')
            logger.info(f"Final output:\n{final_output}")
            
            # Check for errors in output
            error_indicators = ["error", "failed", "cannot", "unable", "permission denied"]
            if any(indicator in final_output.lower() for indicator in error_indicators):
                logger.error(f"Translation upload may have failed. Output: {final_output}")
                shell.close()
                ssh.close()
                return False
            
            # Wait a couple of seconds as user mentioned
            logger.info("Waiting for upload to complete...")
            time.sleep(2)
            
            shell.close()
            ssh.close()
            
            logger.info("✓ Translation file uploaded successfully")
            return True
            
        except paramiko.AuthenticationException:
            logger.error("SSH authentication failed")
            return False
        except paramiko.SSHException as e:
            logger.error(f"SSH error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error during translation upload: {e}")
            return False

