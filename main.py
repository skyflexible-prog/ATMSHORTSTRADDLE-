import asyncio
import logging
from aiohttp import web
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
            data = await request.json()
            await self.bot.application.process_update(
                self.bot.application._update_processor.process_update(data)
            )
            return web.json_response({'status': 'ok'})
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return web.json_response({'status': 'error', 'message': str(e)}, status=400)
    
    async def health_check(self, request):
        """Health check endpoint"""
        return web.json_response({
            'status': 'healthy',
            'service': 'Delta Exchange Short Straddle Bot',
            'version': '1.0.0'
        })

async def setup_webhook(bot: TelegramBot):
    """Setup webhook for the bot"""
    webhook_url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
    try:
        await bot.application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

async def main():
    """Main application entry point"""
    logger.info("Starting Delta Exchange Short Straddle Bot...")
    
    # Initialize bot
    bot = TelegramBot()
    
    # Initialize application
    await bot.application.initialize()
    
    # Setup webhook
    await setup_webhook(bot)
    
    # Create webhook server
    server = WebhookServer(bot)
    
    # Start web server
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    
    logger.info(f"Bot started on {HOST}:{PORT}")
    logger.info(f"Webhook URL: {WEBHOOK_URL}/webhook/{BOT_TOKEN}")
    
    # Keep the application running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.application.shutdown()
        await runner.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
  
