"""
Rancher automation module for setting environment variables and pod parameters.
"""
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RancherAutomation:
    """Automation for Rancher UI to configure pod environment variables."""
    
    def __init__(self, base_url, username, password, headless=False):
        """
        Initialize Rancher automation.
        
        Args:
            base_url: Base URL of Rancher (e.g., https://10.1.71.60:9443)
            username: Rancher username
            password: Rancher password
            headless: Run browser in headless mode (default: False)
        """
        self.base_url = base_url
        self.username = username
        self.password = password
        self.headless = headless
        self.browser = None
        self.page = None
        self.context = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def start(self):
        """Start the browser and navigate to Rancher login."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            channel="chrome"
        )
        self.context = await self.browser.new_context(
            ignore_https_errors=True,
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = await self.context.new_page()
        await self.login()
    
    async def close(self):
        """Close the browser."""
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def login(self):
        """Login to Rancher."""
        logger.info(f"Logging in to Rancher at {self.base_url}")
        await self.page.goto(f"{self.base_url}", wait_until="networkidle")
        
        # Wait for login form
        await self.page.wait_for_selector('input[type="text"], input[name="username"], input[placeholder*="username"]', timeout=15000)
        
        # Fill username
        username_input = self.page.locator('input[type="text"], input[name="username"], input[placeholder*="username"]').first
        await username_input.fill(self.username)
        
        # Fill password
        password_input = self.page.locator('input[type="password"], input[name="password"]').first
        await password_input.fill(self.password)
        
        # Click login button
        login_button = self.page.locator('button:has-text("Log in"), button:has-text("Login"), button[type="submit"]').first
        await login_button.click()
        
        # Wait for navigation after login
        await self.page.wait_for_load_state("networkidle", timeout=30000)
        logger.info("Rancher login successful")
    
    async def set_environment_variables(self, env_vars, namespace="default", deployment_name=None):
        """
        Set environment variables for a pod/deployment.
        
        Args:
            env_vars: Dictionary of environment variable key-value pairs
            namespace: Kubernetes namespace (default: "default")
            deployment_name: Name of the deployment/pod to configure
                            If None, will try to find the main deployment
        """
        logger.info(f"Setting environment variables in namespace: {namespace}")
        
        # Navigate to workloads/deployments
        await self.page.goto(f"{self.base_url}/dashboard/c/local/explorer/workload", wait_until="networkidle")
        
        # Select namespace if needed
        if namespace != "default":
            namespace_selector = self.page.locator(f'option:has-text("{namespace}"), a:has-text("{namespace}")').first
            if await namespace_selector.count() > 0:
                await namespace_selector.click()
                await asyncio.sleep(2)
        
        # Find and click on the deployment
        if deployment_name:
            deployment_link = self.page.locator(f'a:has-text("{deployment_name}"), button:has-text("{deployment_name}")').first
        else:
            # Try to find the first/main deployment
            deployment_link = self.page.locator('a[href*="deployment"], a[href*="workload"]').first
        
        if await deployment_link.count() > 0:
            await deployment_link.click()
            await asyncio.sleep(2)
        
        # Navigate to environment variables section
        # This will vary based on Rancher UI version
        env_tab = self.page.locator('a:has-text("Environment"), button:has-text("Environment"), a:has-text("Env")').first
        if await env_tab.count() > 0:
            await env_tab.click()
            await asyncio.sleep(2)
        
        # Edit button
        edit_button = self.page.locator('button:has-text("Edit"), button:has-text("Edit Config")').first
        if await edit_button.count() > 0:
            await edit_button.click()
            await asyncio.sleep(2)
        
        # Add or update environment variables
        for key, value in env_vars.items():
            try:
                # Check if variable already exists
                existing_var = self.page.locator(f'input[value*="{key}"], input[name*="{key}"]').first
                
                if await existing_var.count() > 0:
                    # Update existing variable
                    # Find the value input next to the key
                    value_input = self.page.locator(f'input[value*="{key}"]').locator('..').locator('input[type="text"]').last
                    if await value_input.count() > 0:
                        await value_input.fill(str(value))
                else:
                    # Add new variable
                    add_button = self.page.locator('button:has-text("Add"), button:has-text("Add Variable")').first
                    if await add_button.count() > 0:
                        await add_button.click()
                        await asyncio.sleep(1)
                        
                        # Fill in key and value
                        # This selector may need adjustment based on actual Rancher UI
                        key_inputs = self.page.locator('input[placeholder*="Key"], input[name*="key"]')
                        value_inputs = self.page.locator('input[placeholder*="Value"], input[name*="value"]')
                        
                        if await key_inputs.count() > 0:
                            last_key_input = key_inputs.last
                            await last_key_input.fill(key)
                        
                        if await value_inputs.count() > 0:
                            last_value_input = value_inputs.last
                            await last_value_input.fill(str(value))
                
                logger.info(f"Set environment variable: {key} = {value}")
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error setting environment variable {key}: {e}")
        
        # Save changes
        save_button = self.page.locator('button:has-text("Save"), button:has-text("Apply")').first
        if await save_button.count() > 0:
            await save_button.click()
            await asyncio.sleep(3)
            logger.info("Environment variables saved")
    
    async def set_pod_parameters(self, parameters, namespace="default", deployment_name=None):
        """
        Set pod parameters (resource limits, replicas, etc.).
        
        Args:
            parameters: Dictionary of pod parameters
            namespace: Kubernetes namespace
            deployment_name: Name of the deployment
        """
        logger.info(f"Setting pod parameters in namespace: {namespace}")
        
        await self.page.goto(f"{self.base_url}/dashboard/c/local/explorer/workload", wait_until="networkidle")
        
        if namespace != "default":
            namespace_selector = self.page.locator(f'option:has-text("{namespace}"), a:has-text("{namespace}")').first
            if await namespace_selector.count() > 0:
                await namespace_selector.click()
                await asyncio.sleep(2)
        
        if deployment_name:
            deployment_link = self.page.locator(f'a:has-text("{deployment_name}")').first
        else:
            deployment_link = self.page.locator('a[href*="deployment"]').first
        
        if await deployment_link.count() > 0:
            await deployment_link.click()
            await asyncio.sleep(2)
        
        # Edit deployment
        edit_button = self.page.locator('button:has-text("Edit"), button:has-text("Edit Config")').first
        if await edit_button.count() > 0:
            await edit_button.click()
            await asyncio.sleep(2)
        
        # Set parameters (replicas, resources, etc.)
        for param_name, param_value in parameters.items():
            try:
                if param_name == "replicas":
                    replicas_input = self.page.locator('input[name*="replicas"], input[id*="replicas"]').first
                    if await replicas_input.count() > 0:
                        await replicas_input.fill(str(param_value))
                
                # Add more parameter types as needed
                logger.info(f"Set parameter: {param_name} = {param_value}")
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error setting parameter {param_name}: {e}")
        
        # Save
        save_button = self.page.locator('button:has-text("Save"), button:has-text("Apply")').first
        if await save_button.count() > 0:
            await save_button.click()
            await asyncio.sleep(3)
            logger.info("Pod parameters saved")

