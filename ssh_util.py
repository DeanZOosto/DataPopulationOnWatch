"""
SSH utility for uploading translation files to OnWatch device.
"""
import os
import logging
import time
import paramiko
import subprocess

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
        Copy file to remote device via SFTP (using paramiko).
        
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
        
        try:
            # Use paramiko for SFTP (same credentials as SSH)
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Suppress INFO level logging for paramiko to avoid confusing auth messages
            paramiko_logger = logging.getLogger('paramiko')
            original_level = paramiko_logger.level
            paramiko_logger.setLevel(logging.WARNING)
            
            try:
                # Connect to SSH (same way as in upload_translation_file)
                if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                    ssh.connect(
                        self.ip_address,
                        username=self.username,
                        key_filename=self.ssh_key_path,
                        timeout=30,
                        look_for_keys=False,  # Don't try public key auth
                        allow_agent=False  # Don't use SSH agent
                    )
                else:
                    if not self.password:
                        raise ValueError("SSH password is required for SFTP")
                    ssh.connect(
                        self.ip_address,
                        username=self.username,
                        password=self.password,
                        timeout=30,
                        look_for_keys=False,  # Don't try public key auth
                        allow_agent=False  # Don't use SSH agent
                    )
            finally:
                paramiko_logger.setLevel(original_level)
            
            # Use SFTP to copy file
            sftp = ssh.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            ssh.close()
            
            logger.info(f"✓ Successfully copied file to {remote_path}")
            return True
            
        except paramiko.AuthenticationException:
            error_msg = f"SFTP authentication failed for {self.username}@{self.ip_address}"
            error_msg += "\n  → Check SSH username and password in config.yaml (ssh section)"
            error_msg += "\n  → Verify credentials are correct for this device"
            error_msg += "\n  → Password may have been changed - update config.yaml with the correct password"
            error_msg += "\n  → If using SSH keys, ensure ssh_key_path is set correctly"
            logger.error(error_msg)
            return False
        except paramiko.SSHException as e:
            error_msg = f"SFTP connection error: {str(e)}"
            error_msg += f"\n  → Target: {self.username}@{self.ip_address}:{remote_path}"
            error_msg += "\n  → Check network connectivity and SSH service status"
            logger.error(error_msg)
            return False
        except Exception as e:
            error_msg = f"SFTP error copying file: {str(e)}"
            error_msg += f"\n  → Local file: {local_path}"
            error_msg += f"\n  → Remote path: {remote_path}"
            error_msg += f"\n  → Target: {self.username}@{self.ip_address}"
            logger.error(error_msg)
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
            
            # Step 1: Become root via sudo su -
            logger.info("Becoming root via 'sudo su -'...")
            shell.send("sudo su -\n")
            time.sleep(1)
            
            # Step 2: Handle sudo password prompt for 'sudo su -'
            output = ""
            sudo_password_sent = False
            root_prompt_received = False
            
            logger.info("Waiting for sudo password prompt...")
            for attempt in range(15):
                time.sleep(0.5)
                chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                if chunk:
                    output += chunk
                    logger.debug(f"Received (attempt {attempt+1}): {chunk[:200]}")
                
                # Check for sudo password prompt
                if "[sudo]" in output.lower() and "password" in output.lower() and not sudo_password_sent:
                    logger.info("Sudo password prompt detected, providing password...")
                    if sudo_password:
                        shell.send(f"{sudo_password}\n")
                        time.sleep(1)
                        sudo_password_sent = True
                        output = ""  # Clear buffer after sending password
                        logger.info("Sudo password sent, waiting for root prompt...")
                        continue
                    else:
                        logger.error("Sudo password required but not provided")
                        shell.close()
                        ssh.close()
                        return False
                
                # If we see "Sorry, try again", password was wrong
                if "Sorry, try again" in output:
                    logger.error("Sudo password was incorrect")
                    shell.close()
                    ssh.close()
                    return False
                
                # Check if we're now root (root prompt usually has '#' or 'root@')
                if "#" in output or "root@" in output.lower() or output.strip().endswith("#"):
                    logger.info("Successfully became root")
                    root_prompt_received = True
                    output = ""  # Clear buffer
                    break
            
            if not root_prompt_received:
                logger.warning("Root prompt not clearly detected, but continuing...")
            
            # Step 3: Change to script directory (now as root)
            logger.info(f"Changing to directory: {script_dir}")
            shell.send(f"cd {script_dir}\n")
            time.sleep(1)
            shell.recv(1024)  # Clear any output
            
            # Step 4: Run ./translation-util upload (no sudo needed, we're already root)
            logger.info(f"Running: ./{script_name} upload (as root)")
            shell.send(f"./{script_name} upload\n")
            time.sleep(1)
            
            # Step 5: Wait for script to show "Current Translation Files Available" and "Please Enter Translation File To Upload:"
            logger.info("Waiting for translation-util script output...")
            output = ""  # Reset output buffer for script output
            prompt_found = False
            
            # Continue reading output until we see the exact prompt
            for attempt in range(20):
                time.sleep(0.5)
                chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                if chunk:
                    output += chunk
                    logger.debug(f"Reading script output (attempt {attempt+1}): {chunk[:200]}")
                
                # Look for the exact prompt: "Please Enter Translation File To Upload:"
                if "Please Enter Translation File To Upload" in output:
                    logger.info("File input prompt detected!")
                    logger.info(f"Full script output:\n{output}")
                    prompt_found = True
                    break
                
                # Also check if script has started showing available files
                if "Current Translation Files Available" in output:
                    logger.info("Script is showing available files, waiting for input prompt...")
                    # Continue waiting for the prompt
            
            # Log final output before sending file path
            if output:
                logger.info(f"Script output before sending file path:\n{output}")
            
            if not prompt_found:
                logger.warning("File input prompt 'Please Enter Translation File To Upload:' not found")
                logger.warning("Proceeding anyway, but upload may fail...")
            
            # Step 6: Provide the exact file path: /tmp/Polski-updated3.json.json
            logger.info(f"Providing file path: {remote_tmp_path}")
            shell.send(f"{remote_tmp_path}\n")
            time.sleep(3)  # Wait for processing
            
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
            
        except paramiko.AuthenticationException as e:
            error_msg = f"SSH authentication failed for {self.username}@{self.ip_address}: {e}"
            error_msg += "\n  → Check SSH username and password in config.yaml (ssh section)"
            error_msg += "\n  → Verify credentials are correct for this device"
            error_msg += "\n  → Password may have been changed - update config.yaml with the correct password"
            error_msg += "\n  → If using SSH keys, ensure ssh_key_path is set correctly"
            logger.error(error_msg)
            return False
        except paramiko.SSHException as e:
            logger.error(f"SSH error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error during translation upload: {e}", exc_info=True)
            return False

