import asyncio
import logging
import json
from aiohttp import web
from telegram import Update
from telegram_handler import TelegramBot
from config import HOST, PORT, WEBHOOK_URL, BOT_TOKEN

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class WebhookServer:
    def __init__(self, bot: TelegramBot):
        self.bot = bot
        self.app = web.Application()
        self.setup_routes()
    
    def setup_routes(self):
        """Setup web routes"""
        self.app.router.add_post(f'/webhook/{BOT_TOKEN}', self.webhook_handler)
        self.app.router.add_get('/', self.health_check)
        self.app.router.add_get('/health', self.health_check)
    
    async def webhook_handler(self, request):
        """Handle incoming webhook requests"""
        try:
            # Get the raw JSON data
            data = await request.json()
            logger.info(f"Received webhook update: {data.get('update_id', 'unknown')}")
            
            # Create Update object from the received data
            update = Update.de_json(data, self.bot.application.bot)
            
            if update:
                # Process the update using the correct method
                await self.bot.application.process_update(update)
                logger.info(f"Successfully processed update {update.update_id}")
            else:
                logger.warning("Received invalid update data")
                return web.json_response(
                    {'status': 'error', 'message': 'Invalid update'}, 
                    status=400
                )
            
            return web.json_response({'status': 'ok'})
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return web.json_response(
                {'status': 'error', 'message': 'Invalid JSON'}, 
                status=400
            )
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return web.json_response(
                {'status': 'error', 'message': str(e)}, 
                status=500
            )
    
    async def health_check(self, request):
        """Health check endpoint"""
        return web.json_response({
            'status': 'healthy',
            'service': 'Delta Exchange Short Straddle Bot',
            'version': '1.0.0',
            'webhook_configured': True
        })

async def setup_webhook(bot: TelegramBot):
    """Setup webhook for the bot"""
    webhook_url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
    try:
        # Remove existing webhook first
        await bot.application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Existing webhook deleted successfully")
        
        # Set new webhook
        success = await bot.application.bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True,
            max_connections=100,
            secret_token=None  # You can add a secret token for security
        )
        
        if success:
            logger.info(f"Webhook set successfully to: {webhook_url}")
            
            # Verify webhook info
            webhook_info = await bot.application.bot.get_webhook_info()
            logger.info(f"Webhook verification - URL: {webhook_info.url}")
            logger.info(f"Pending updates: {webhook_info.pending_update_count}")
        else:
            logger.error("Failed to set webhook")
            raise Exception("Webhook setup failed")
            
    except Exception as e:
        logger.error(f"Webhook setup error: {e}")
        raise

async def main():
    """Main application entry point"""
    logger.info("Starting Delta Exchange Short Straddle Bot...")
    
    try:
        # Initialize bot
        bot = TelegramBot()
        
        # Initialize application without updater (for webhook mode)
        await bot.application.initialize()
        await bot.application.start()
        
        logger.info("Bot application initialized successfully")
        
        # Setup webhook
        await setup_webhook(bot)
        
        # Create webhook server
        server = WebhookServer(bot)
        
        # Start web server
        runner = web.AppRunner(server.app)
        await runner.setup()
        site = web.TCPSite(runner, HOST, PORT)
        await site.start()
        
        logger.info(f"🚀 Bot started successfully on {HOST}:{PORT}")
        logger.info(f"🔗 Webhook URL: {WEBHOOK_URL}/webhook/{BOT_TOKEN}")
        logger.info("Bot is ready to receive updates!")
        
        # Keep the application running
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal...")
        finally:
            logger.info("Shutting down bot...")
            await bot.application.stop()
            await bot.application.shutdown()
            await runner.cleanup()
            logger.info("Bot shutdown complete")
            
    except Exception as e:
        logger.error(f"Fatal application error: {e}")
        raise

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal startup error: {e}")
        exit(1)
      
