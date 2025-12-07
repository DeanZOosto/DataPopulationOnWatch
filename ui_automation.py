import asyncio
import logging
import os
import re
import base64
import json
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


class OnWatchUIAutomation:
    """UI Automation for OnWatch settings via browser."""
    
    def __init__(self, base_url, username, password, headless=True):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None
    
    async def start(self):
        """Start browser and create page."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        context = await self.browser.new_context(ignore_https_errors=True)
        self.page = await context.new_page()
    
    async def stop(self):
        """Stop browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
    
    async def login(self):
        """Login to OnWatch system."""
        logger.info(f"Logging in to {self.base_url}")
        # Login page is at /bt/login
        await self.page.goto(f"{self.base_url}/bt/login", wait_until="networkidle")
        await asyncio.sleep(2)  # Give page time to load
        
        # Wait for and fill username - try multiple selectors
        try:
            await self.page.wait_for_selector('input[name="username"], input[type="text"], input[placeholder*="username"], input[placeholder*="Username"]', timeout=15000)
        except:
            # If selector not found, try to find any input
            await self.page.wait_for_selector('input', timeout=15000)
        
        username_input = self.page.locator('input[name="username"], input[type="text"], input[placeholder*="username"], input[placeholder*="Username"]').first
        if await username_input.count() == 0:
            # Fallback: try first text input
            username_input = self.page.locator('input[type="text"]').first
        
        await username_input.fill(self.username)
        
        # Wait for and fill password
        password_input = self.page.locator('input[name="password"], input[type="password"]').first
        await password_input.fill(self.password)
        
        # Click login button
        login_button = self.page.locator('button[type="submit"], button:has-text("Login"), button:has-text("Sign in"), button:has-text("Log in")').first
        await login_button.click()
        
        # Wait for navigation after login
        await self.page.wait_for_load_state("networkidle", timeout=30000)
        await asyncio.sleep(2)  # Additional wait for page to fully load
        logger.info("Login successful")
    
    async def set_kv_parameters(self, kv_params):
        """
        Set KV parameters via UI.
        Uses textarea editor - searches for key, updates value, clicks Apply for that field.
        
        Args:
            kv_params: Dictionary of key-value parameters
        """
        logger.info("Setting KV parameters via UI")
        await self.login()  # Make sure we're logged in
        await self.page.goto(f"{self.base_url}/bt/settings/kv", wait_until="networkidle")
        await asyncio.sleep(3)  # Wait for page to fully load
        
        updated_count = 0
        
        # Process each KV parameter individually
        # Each parameter is in its own row with label, input, and Apply button
        for key, value in kv_params.items():
            try:
                logger.info(f"Processing KV parameter: {key} = {value}")
                full_key = key
                
                # Use JavaScript to find, update, and apply - all in one operation
                try:
                    target_value = str(value).strip()
                    result = await self.page.evaluate('''
                        (keyText, targetValue) => {
                            // Find all containers
                            const containers = Array.from(document.querySelectorAll(".KvListItem_container__2494X"));
                            
                            // Find the one that contains our key
                            const targetContainer = containers.find(cont => {
                                const text = cont.textContent || "";
                                return text.includes(keyText);
                            });
                            
                            if (!targetContainer) {
                                return { success: false, error: "Container not found" };
                            }
                            
                            // Find InputBase in THIS container only
                            const inputBase = targetContainer.querySelector(".InputBase-module_inputBase__252tg");
                            if (!inputBase) {
                                return { success: false, error: "InputBase not found in container" };
                            }
                            
                            // Find the actual input element
                            let input = inputBase.querySelector("textarea");
                            let inputType = "textarea";
                            if (!input) {
                                input = inputBase.querySelector("input");
                                inputType = "input";
                            }
                            if (!input && inputBase.contentEditable === "true") {
                                input = inputBase;
                                inputType = "contenteditable";
                            }
                            
                            if (!input) {
                                return { success: false, error: "Input element not found" };
                            }
                            
                            // Verify it's in the right container
                            const inputContainer = input.closest(".KvListItem_container__2494X");
                            if (inputContainer !== targetContainer) {
                                return { success: false, error: "Input is in wrong container" };
                            }
                            
                            // Get the current value
                            let currentValue = "";
                            if (inputType === "contenteditable") {
                                currentValue = (input.textContent || input.innerText || "").trim();
                            } else {
                                currentValue = (input.value || "").trim();
                            }
                            
                            // If value is already correct, just verify and return
                            if (currentValue === targetValue) {
                                return {
                                    success: true,
                                    alreadyCorrect: true,
                                    currentValue: currentValue,
                                    inputType: inputType
                                };
                            }
                            
                            // Update the value
                            if (inputType === "contenteditable") {
                                input.textContent = targetValue;
                                input.innerText = targetValue;
                                // Trigger events
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true }));
                                input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                                input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
                            } else if (inputType === "textarea") {
                                // Use native setter to trigger React
                                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                                nativeSetter.call(input, targetValue);
                                // Trigger events
                                input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                            } else {
                                // Regular input
                                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                nativeSetter.call(input, targetValue);
                                // Trigger events
                                input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                            }
                            
                            // Small delay to let React detect the change and enable the button
                            // Note: We can't use setTimeout in evaluate, so we'll wait in Python after this
                            
                            // Find the Apply button in the same container
                            let applyButton = null;
                            // Try finding by text content
                            const buttons = targetContainer.querySelectorAll('button');
                            for (let btn of buttons) {
                                const btnText = (btn.textContent || "").toUpperCase().trim();
                                if (btnText === "APPLY" || btnText.includes("APPLY")) {
                                    applyButton = btn;
                                    break;
                                }
                            }
                            
                            // Also try aria-label
                            if (!applyButton) {
                                for (let btn of buttons) {
                                    const ariaLabel = (btn.getAttribute('aria-label') || "").toUpperCase();
                                    if (ariaLabel.includes("APPLY")) {
                                        applyButton = btn;
                                        break;
                                    }
                                }
                            }
                            
                            if (!applyButton) {
                                return { success: false, error: "Apply button not found" };
                            }
                            
                            // Check if button is enabled
                            const isDisabled = applyButton.disabled || applyButton.getAttribute('disabled') !== null;
                            if (isDisabled) {
                                return { success: false, error: "Apply button is disabled", buttonFound: true };
                            }
                            
                            // Click the Apply button
                            applyButton.click();
                            
                            // Get the new value after clicking
                            let newValue = "";
                            if (inputType === "contenteditable") {
                                newValue = (input.textContent || input.innerText || "").trim();
                            } else {
                                newValue = (input.value || "").trim();
                            }
                            
                            return {
                                success: true,
                                alreadyCorrect: false,
                                currentValue: currentValue,
                                newValue: newValue,
                                inputType: inputType,
                                applied: true
                            };
                        }
                    ''', full_key, target_value)
                    
                    if not result.get('success'):
                        error_msg = result.get('error', 'Unknown error')
                        if result.get('buttonFound') and result.get('error') == 'Apply button is disabled':
                            # Button is disabled - wait a bit and try again
                            logger.info(f"Apply button is disabled for key '{full_key}'. Waiting for UI to update...")
                            await asyncio.sleep(1.0)
                            
                            # Try again with a retry - just click the button if it's now enabled
                            retry_result = await self.page.evaluate('''
                                (keyText) => {
                                    const containers = Array.from(document.querySelectorAll(".KvListItem_container__2494X"));
                                    const targetContainer = containers.find(cont => {
                                        const text = cont.textContent || "";
                                        return text.includes(keyText);
                                    });
                                    if (!targetContainer) return { success: false, error: "Container not found on retry" };
                                    
                                    const buttons = targetContainer.querySelectorAll('button');
                                    let applyButton = null;
                                    for (let btn of buttons) {
                                        const btnText = (btn.textContent || "").toUpperCase().trim();
                                        if (btnText === "APPLY" || btnText.includes("APPLY")) {
                                            applyButton = btn;
                                            break;
                                        }
                                    }
                                    
                                    if (!applyButton) return { success: false, error: "Apply button not found on retry" };
                                    
                                    const isDisabled = applyButton.disabled || applyButton.getAttribute('disabled') !== null;
                                    if (isDisabled) {
                                        return { success: false, error: "Apply button still disabled" };
                                    }
                                    
                                    applyButton.click();
                                    return { success: true, applied: true };
                                }
                            ''', full_key)
                            
                            if retry_result.get('success'):
                                logger.info(f"✓ Successfully applied changes for '{full_key}' on retry")
                                updated_count += 1
                            else:
                                logger.warning(f"Apply button still disabled for key '{full_key}'. Value may not have changed.")
                                logger.info(f"Current value: '{result.get('currentValue', 'unknown')}', Target: '{target_value}'")
                                updated_count += 1
                        else:
                            logger.error(f"Could not update key '{full_key}': {error_msg}")
                            updated_count += 1
                        await asyncio.sleep(1.5)
                        continue
                    
                    if result.get('alreadyCorrect'):
                        logger.info(f"✓ Value already correct for '{full_key}': {target_value}")
                        updated_count += 1
                    else:
                        logger.info(f"✓ Updated '{full_key}': '{result.get('currentValue')}' -> '{result.get('newValue')}'")
                        if result.get('applied'):
                            logger.info(f"  Applied changes for '{full_key}'")
                        updated_count += 1
                    
                    await asyncio.sleep(1.5)  # Wait between parameters
                    
                except Exception as e:
                    logger.error(f"Error processing key '{full_key}': {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    updated_count += 1
                    continue
                
            except Exception as e:
                logger.error(f"Error setting KV parameter {key}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                updated_count += 1  # Count as attempted
        
        logger.info(f"KV parameters processed: {updated_count} updated and applied")
        await asyncio.sleep(1)
        logger.info("✓ KV parameters configuration completed")
    
    async def configure_system_settings(self, settings):
        """
        Configure system settings via UI.
        
        Args:
            settings: Dictionary of system settings with sections: general, map, system_interface, engine
        """
        logger.info("Configuring system settings via UI")
        await self.login()  # Make sure we're logged in
        
        # Configure General Settings
        if 'general' in settings:
            await self._configure_general_settings(settings['general'])
        
        # Configure Map Settings
        if 'map' in settings:
            await self._configure_map_settings(settings['map'])
        
        # Configure System Interface
        if 'system_interface' in settings:
            await self._configure_system_interface(settings['system_interface'])
        
        # Configure Engine Settings
        if 'engine' in settings:
            await self._configure_engine_settings(settings['engine'])
        
        logger.info("✓ System settings configuration completed")
    
    async def _configure_general_settings(self, general_settings):
        """Configure general system settings."""
        logger.info("Configuring general settings...")
        await self.page.goto(f"{self.base_url}/bt/settings/general", wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Blur all faces except selected
        if 'blur_all_faces_except_selected' in general_settings:
            try:
                checkbox = self.page.locator('input[type="checkbox"], input[type="switch"]').filter(has_text="Blur all faces").first
                if await checkbox.count() > 0:
                    is_checked = await checkbox.is_checked()
                    should_be_checked = general_settings['blur_all_faces_except_selected']
                    if is_checked != should_be_checked:
                        await checkbox.click()
                        logger.info(f"Set 'Blur all faces except selected': {should_be_checked}")
            except Exception as e:
                logger.debug(f"Could not set blur_all_faces_except_selected: {e}")
        
        # Discard detections not in watch list
        if 'discard_detections_not_in_watch_list' in general_settings:
            try:
                checkbox = self.page.locator('input[type="checkbox"], input[type="switch"]').filter(has_text="Discard detections").first
                if await checkbox.count() > 0:
                    is_checked = await checkbox.is_checked()
                    should_be_checked = general_settings['discard_detections_not_in_watch_list']
                    if is_checked != should_be_checked:
                        await checkbox.click()
                        logger.info(f"Set 'Discard detections not in watch list': {should_be_checked}")
            except Exception as e:
                logger.debug(f"Could not set discard_detections_not_in_watch_list: {e}")
        
        # Body Image Retention Period
        if 'body_image_retention_period' in general_settings:
            try:
                # Look for input field related to body image retention
                retention_input = self.page.locator('input, textarea').filter(has_text="Body Image Retention").first
                if await retention_input.count() == 0:
                    # Try finding by label
                    retention_input = self.page.locator('label:has-text("Body Image Retention") + input, label:has-text("Body Image Retention") ~ input').first
                if await retention_input.count() > 0:
                    await retention_input.fill(general_settings['body_image_retention_period'])
                    logger.info(f"Set 'Body Image Retention Period': {general_settings['body_image_retention_period']}")
            except Exception as e:
                logger.debug(f"Could not set body_image_retention_period: {e}")
        
        # Default Face Threshold
        if 'default_face_threshold' in general_settings:
            try:
                threshold_input = self.page.locator('input[type="number"], input').filter(has_text="Default Face Threshold").first
                if await threshold_input.count() == 0:
                    threshold_input = self.page.locator('label:has-text("Default Face Threshold") + input, label:has-text("Default Face Threshold") ~ input').first
                if await threshold_input.count() > 0:
                    await threshold_input.fill(str(general_settings['default_face_threshold']))
                    logger.info(f"Set 'Default Face Threshold': {general_settings['default_face_threshold']}")
            except Exception as e:
                logger.debug(f"Could not set default_face_threshold: {e}")
        
        # Default Body Threshold
        if 'default_body_threshold' in general_settings:
            try:
                threshold_input = self.page.locator('input[type="number"], input').filter(has_text="Default Body Threshold").first
                if await threshold_input.count() == 0:
                    threshold_input = self.page.locator('label:has-text("Default Body Threshold") + input, label:has-text("Default Body Threshold") ~ input').first
                if await threshold_input.count() > 0:
                    await threshold_input.fill(str(general_settings['default_body_threshold']))
                    logger.info(f"Set 'Default Body Threshold': {general_settings['default_body_threshold']}")
            except Exception as e:
                logger.debug(f"Could not set default_body_threshold: {e}")
        
        # Default Liveness Threshold
        if 'default_liveness_threshold' in general_settings:
            try:
                threshold_input = self.page.locator('input[type="number"], input').filter(has_text="Default Liveness Threshold").first
                if await threshold_input.count() == 0:
                    threshold_input = self.page.locator('label:has-text("Default Liveness Threshold") + input, label:has-text("Default Liveness Threshold") ~ input').first
                if await threshold_input.count() > 0:
                    await threshold_input.fill(str(general_settings['default_liveness_threshold']))
                    logger.info(f"Set 'Default Liveness Threshold': {general_settings['default_liveness_threshold']}")
            except Exception as e:
                logger.debug(f"Could not set default_liveness_threshold: {e}")
        
        # Save/Apply button
        try:
            save_button = self.page.locator('button:has-text("Save"), button:has-text("Apply"), button[type="submit"]').first
            if await save_button.count() > 0 and await save_button.is_enabled():
                await save_button.click()
                await asyncio.sleep(1)
                logger.info("Applied general settings")
        except Exception as e:
            logger.debug(f"Could not click save button: {e}")
    
    async def _configure_map_settings(self, map_settings):
        """Configure map settings."""
        logger.info("Configuring map settings...")
        await self.page.goto(f"{self.base_url}/bt/settings/map", wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Seed location (lat/long)
        if 'seed_location' in map_settings:
            seed = map_settings['seed_location']
            try:
                # Find latitude input
                lat_input = self.page.locator('input[type="number"], input').filter(has_text="Latitude").first
                if await lat_input.count() == 0:
                    lat_input = self.page.locator('label:has-text("Lat"), label:has-text("Latitude") + input, label:has-text("Latitude") ~ input').first
                if await lat_input.count() > 0:
                    await lat_input.fill(str(seed.get('lat', '')))
                    logger.info(f"Set seed location latitude: {seed.get('lat')}")
                
                # Find longitude input
                long_input = self.page.locator('input[type="number"], input').filter(has_text="Longitude").first
                if await long_input.count() == 0:
                    long_input = self.page.locator('label:has-text("Long"), label:has-text("Longitude") + input, label:has-text("Longitude") ~ input').first
                if await long_input.count() > 0:
                    await long_input.fill(str(seed.get('long', '')))
                    logger.info(f"Set seed location longitude: {seed.get('long')}")
            except Exception as e:
                logger.debug(f"Could not set seed location: {e}")
        
        # Acknowledge
        if 'acknowledge' in map_settings:
            try:
                checkbox = self.page.locator('input[type="checkbox"], input[type="switch"]').filter(has_text="Acknowledge").first
                if await checkbox.count() > 0:
                    is_checked = await checkbox.is_checked()
                    should_be_checked = map_settings['acknowledge']
                    if is_checked != should_be_checked:
                        await checkbox.click()
                        logger.info(f"Set 'Acknowledge': {should_be_checked}")
            except Exception as e:
                logger.debug(f"Could not set acknowledge: {e}")
        
        # Action title
        if 'action_title' in map_settings:
            try:
                action_input = self.page.locator('input, textarea').filter(has_text="Action title").first
                if await action_input.count() == 0:
                    action_input = self.page.locator('label:has-text("Action title") + input, label:has-text("Action title") ~ input').first
                if await action_input.count() > 0:
                    await action_input.fill(map_settings['action_title'])
                    logger.info(f"Set 'Action title': {map_settings['action_title']}")
            except Exception as e:
                logger.debug(f"Could not set action_title: {e}")
        
        # Masks Access Control
        if 'masks_access_control' in map_settings:
            try:
                checkbox = self.page.locator('input[type="checkbox"], input[type="switch"]').filter(has_text="Masks Access Control").first
                if await checkbox.count() > 0:
                    is_checked = await checkbox.is_checked()
                    should_be_checked = map_settings['masks_access_control']
                    if is_checked != should_be_checked:
                        await checkbox.click()
                        logger.info(f"Set 'Masks Access Control': {should_be_checked}")
            except Exception as e:
                logger.debug(f"Could not set masks_access_control: {e}")
        
        # Save/Apply button
        try:
            save_button = self.page.locator('button:has-text("Save"), button:has-text("Apply"), button[type="submit"]').first
            if await save_button.count() > 0 and await save_button.is_enabled():
                await save_button.click()
                await asyncio.sleep(1)
                logger.info("Applied map settings")
        except Exception as e:
            logger.debug(f"Could not click save button: {e}")
    
    async def _configure_system_interface(self, interface_settings):
        """Configure system interface settings."""
        logger.info("Configuring system interface settings...")
        await self.page.goto(f"{self.base_url}/bt/settings/interface", wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Product name
        if 'product_name' in interface_settings and interface_settings['product_name']:
            try:
                product_input = self.page.locator('input, textarea').filter(has_text="Product name").first
                if await product_input.count() == 0:
                    product_input = self.page.locator('label:has-text("Product name") + input, label:has-text("Product name") ~ input').first
                if await product_input.count() > 0:
                    await product_input.fill(interface_settings['product_name'])
                    logger.info(f"Set 'Product name': {interface_settings['product_name']}")
            except Exception as e:
                logger.debug(f"Could not set product_name: {e}")
        
        # Translation file upload (if path provided)
        if 'translation_file' in interface_settings and interface_settings['translation_file']:
            try:
                file_input = self.page.locator('input[type="file"]').first
                if await file_input.count() > 0:
                    await file_input.set_input_files(interface_settings['translation_file'])
                    logger.info(f"Uploaded translation file: {interface_settings['translation_file']}")
            except Exception as e:
                logger.debug(f"Could not upload translation file: {e}")
        
        # Icons upload (if path provided)
        if 'icons' in interface_settings and interface_settings['icons']:
            try:
                file_input = self.page.locator('input[type="file"]').last  # Usually last file input
                if await file_input.count() > 0:
                    await file_input.set_input_files(interface_settings['icons'])
                    logger.info(f"Uploaded icons: {interface_settings['icons']}")
            except Exception as e:
                logger.debug(f"Could not upload icons: {e}")
        
        # Save/Apply button
        try:
            save_button = self.page.locator('button:has-text("Save"), button:has-text("Apply"), button[type="submit"]').first
            if await save_button.count() > 0 and await save_button.is_enabled():
                await save_button.click()
                await asyncio.sleep(1)
                logger.info("Applied system interface settings")
        except Exception as e:
            logger.debug(f"Could not click save button: {e}")
    
    async def _configure_engine_settings(self, engine_settings):
        """Configure engine/storage settings."""
        logger.info("Configuring engine settings...")
        await self.page.goto(f"{self.base_url}/bt/settings/engine", wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Video storage settings
        if 'video_storage' in engine_settings:
            video_storage = engine_settings['video_storage']
            # All videos days
            if 'all_videos_days' in video_storage:
                try:
                    all_videos_input = self.page.locator('input[type="number"], input').filter(has_text="All videos").first
                    if await all_videos_input.count() == 0:
                        all_videos_input = self.page.locator('label:has-text("All videos") + input, label:has-text("All videos") ~ input').first
                    if await all_videos_input.count() > 0:
                        await all_videos_input.fill(str(video_storage['all_videos_days']))
                        logger.info(f"Set 'All videos storage days': {video_storage['all_videos_days']}")
                except Exception as e:
                    logger.debug(f"Could not set all_videos_days: {e}")
            
            # Videos with detections days
            if 'videos_with_detections_days' in video_storage:
                try:
                    detections_input = self.page.locator('input[type="number"], input').filter(has_text="Videos containing only detections").first
                    if await detections_input.count() == 0:
                        detections_input = self.page.locator('label:has-text("Videos containing only detections") + input, label:has-text("Videos containing only detections") ~ input').first
                    if await detections_input.count() > 0:
                        await detections_input.fill(str(video_storage['videos_with_detections_days']))
                        logger.info(f"Set 'Videos with detections storage days': {video_storage['videos_with_detections_days']}")
                except Exception as e:
                    logger.debug(f"Could not set videos_with_detections_days: {e}")
        
        # Detection storage days
        if 'detection_storage_days' in engine_settings:
            try:
                detection_input = self.page.locator('input[type="number"], input').filter(has_text="Detection storage").first
                if await detection_input.count() == 0:
                    detection_input = self.page.locator('label:has-text("Detection storage") + input, label:has-text("Detection storage") ~ input').first
                if await detection_input.count() > 0:
                    await detection_input.fill(str(engine_settings['detection_storage_days']))
                    logger.info(f"Set 'Detection storage days': {engine_settings['detection_storage_days']}")
            except Exception as e:
                logger.debug(f"Could not set detection_storage_days: {e}")
        
        # Alert storage days
        if 'alert_storage_days' in engine_settings:
            try:
                alert_input = self.page.locator('input[type="number"], input').filter(has_text="Alert storage").first
                if await alert_input.count() == 0:
                    alert_input = self.page.locator('label:has-text("Alert storage") + input, label:has-text("Alert storage") ~ input').first
                if await alert_input.count() > 0:
                    await alert_input.fill(str(engine_settings['alert_storage_days']))
                    logger.info(f"Set 'Alert storage days': {engine_settings['alert_storage_days']}")
            except Exception as e:
                logger.debug(f"Could not set alert_storage_days: {e}")
        
        # Inquiry storage days
        if 'inquiry_storage_days' in engine_settings:
            try:
                inquiry_input = self.page.locator('input[type="number"], input').filter(has_text="Inquiry storage").first
                if await inquiry_input.count() == 0:
                    inquiry_input = self.page.locator('label:has-text("Inquiry storage") + input, label:has-text("Inquiry storage") ~ input').first
                if await inquiry_input.count() > 0:
                    await inquiry_input.fill(str(engine_settings['inquiry_storage_days']))
                    logger.info(f"Set 'Inquiry storage days': {engine_settings['inquiry_storage_days']}")
            except Exception as e:
                logger.debug(f"Could not set inquiry_storage_days: {e}")
        
        # Save/Apply button
        try:
            save_button = self.page.locator('button:has-text("Save"), button:has-text("Apply"), button[type="submit"]').first
            if await save_button.count() > 0 and await save_button.is_enabled():
                await save_button.click()
                await asyncio.sleep(1)
                logger.info("Applied engine settings")
        except Exception as e:
            logger.debug(f"Could not click save button: {e}")
    
    async def configure_groups(self, groups):
        """
        Configure groups and profiles via UI.
        
        Args:
            groups: Dictionary of groups configuration
        """
        logger.info("Configuring groups via UI")
        # Implementation for groups
        pass
    
    async def configure_accounts(self, accounts):
        """
        Configure accounts via UI.
        
        Args:
            accounts: Dictionary of accounts configuration
        """
        logger.info("Configuring accounts via UI")
        # Implementation for accounts
        pass
    
    async def configure_devices(self, devices):
        """
        Configure devices/cameras via UI.
        
        Args:
            devices: Dictionary of devices configuration
        """
        logger.info("Configuring devices via UI")
        # Implementation for devices
        pass
    
    async def configure_inquiries(self, inquiries):
        """
        Configure inquiries via UI.
        
        Args:
            inquiries: Dictionary of inquiries configuration
        """
        logger.info("Configuring inquiries via UI")
        # Implementation for inquiries
        pass
    
    async def upload_mass_import(self, file_path):
        """
        Upload mass import file via UI.
        
        Args:
            file_path: Path to mass import file
        """
        logger.info("Uploading mass import file via UI")
        # Implementation for mass import
        pass
    
    async def upload_files(self, files):
        """
        Upload files (translations, icons) via UI.
        
        Args:
            files: Dictionary of file paths to upload
        """
        logger.info("Uploading files via UI")
        # Implementation for file uploads
        pass
