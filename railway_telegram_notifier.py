import os
import sys
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

# Load environment variables from .env file if it exists
load_dotenv()

# Get environment variables with fallbacks
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', 600))
EOD_REPORT_TIME = os.environ.get('EOD_REPORT_TIME', '16:00')

# Import all system components
sys.path.append('/app')
import gold_price_monitor
import technical_analysis
import news_monitor
import notification_system
import report_generator

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token, chat_id=None, check_interval=CHECK_INTERVAL):
        """
        Initialize the Telegram Notifier
        
        Parameters:
        token (str): Telegram Bot API token
        chat_id (str): Chat ID to send messages to (optional)
        check_interval (int): Interval between checks in seconds (default: from environment)
        """
        self.token = token
        self.chat_id = chat_id
        self.check_interval = check_interval
        self.bot = telegram.Bot(token=token)
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        
        # Initialize trading assistant components
        self.gold_monitor = gold_price_monitor.GoldPriceMonitor(interval='5m')
        self.news_monitor = news_monitor.NewsMonitor()
        self.notifier = notification_system.NotificationSystem(check_interval=check_interval)
        self.reporter = report_generator.ReportGenerator()
        
        # Setup command handlers
        self.setup_handlers()
        
        # Create necessary directories
        os.makedirs('/app/data', exist_ok=True)
        os.makedirs('/app/charts', exist_ok=True)
        os.makedirs('/app/reports', exist_ok=True)
        os.makedirs('/app/logs', exist_ok=True)
        
        # Store registered users
        self.users_file = '/app/data/telegram_users.json'
        self.users = self.load_users()
        
    def load_users(self):
        """Load registered users from file"""
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error("Error decoding users file, creating new one")
                return {'users': []}
        return {'users': []}
        
    def save_users(self):
        """Save registered users to file"""
        try:
            with open(self.users_file, 'w') as f:
                json.dump(self.users, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving users file: {e}")
            
    def register_user(self, chat_id, username=None):
        """Register a new user"""
        if str(chat_id) not in [str(user['chat_id']) for user in self.users['users']]:
            self.users['users'].append({
                'chat_id': chat_id,
                'username': username,
                'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'settings': {
                    'price_alerts': True,
                    'signal_alerts': True,
                    'news_alerts': True,
                    'eod_reports': True
                }
            })
            self.save_users()
            return True
        return False
        
    def setup_handlers(self):
        """Setup command handlers"""
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        self.dispatcher.add_handler(CommandHandler("price", self.price_command))
        self.dispatcher.add_handler(CommandHandler("signal", self.signal_command))
        self.dispatcher.add_handler(CommandHandler("news", self.news_command))
        self.dispatcher.add_handler(CommandHandler("report", self.report_command))
        self.dispatcher.add_handler(CommandHandler("settings", self.settings_command))
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_message))
        self.dispatcher.add_error_handler(self.error_handler)
        
    def start_command(self, update, context):
        """Handle /start command"""
        chat_id = update.effective_chat.id
        username = update.effective_user.username
        
        if self.register_user(chat_id, username):
            message = (
                "🎉 Welcome to XAU/USD Trading Assistant! 🎉\n\n"
                "I'll send you alerts for:\n"
                "📈 Trading signals (Buy/Sell)\n"
                "💰 Price movements\n"
                "📰 Important gold-related news\n"
                "📊 End-of-day reports\n\n"
                "Use /help to see available commands."
            )
        else:
            message = (
                "Welcome back to XAU/USD Trading Assistant!\n\n"
                "Use /help to see available commands."
            )
            
        context.bot.send_message(chat_id=chat_id, text=message)
        
    def help_command(self, update, context):
        """Handle /help command"""
        help_text = (
            "XAU/USD Trading Assistant Commands:\n\n"
            "/price - Get current gold price\n"
            "/signal - Get latest trading signal\n"
            "/news - Get latest gold news\n"
            "/report - Get latest EOD report\n"
            "/settings - Manage notification settings\n"
            "/help - Show this help message"
        )
        update.message.reply_text(help_text)
        
    def price_command(self, update, context):
        """Handle /price command"""
        try:
            update.message.reply_text("Fetching current gold price...")
            
            # Get current price
            self.gold_monitor.fetch_live_data()
            current_price = self.gold_monitor.get_current_price()
            
            # Generate price chart
            chart_path = "/app/charts/current_price_chart.png"
            self.gold_monitor.plot_price_chart(save_path=chart_path)
            
            # Send price information
            message = f"💰 Current XAU/USD Price: ${current_price:.2f}"
            
            # Send message with chart
            with open(chart_path, 'rb') as chart:
                update.message.reply_photo(photo=chart, caption=message)
                
        except Exception as e:
            logger.error(f"Error in price command: {e}")
            update.message.reply_text(f"Error fetching price: {str(e)}")
            
    def signal_command(self, update, context):
        """Handle /signal command"""
        try:
            update.message.reply_text("Generating latest trading signal...")
            
            # Fetch data and generate signal
            data = self.gold_monitor.fetch_live_data()
            ta = technical_analysis.TechnicalAnalysis(data)
            signals = ta.generate_signals()
            
            if signals is None or signals.empty:
                update.message.reply_text("Failed to generate trading signals.")
                return
                
            # Get latest signal
            latest_signal = signals.iloc[-1]
            signal_value = latest_signal['Signal']
            
            # Determine signal type
            if signal_value > 0:
                signal_type = "🟢 BUY"
            elif signal_value < 0:
                signal_type = "🔴 SELL"
            else:
                signal_type = "⚪ NEUTRAL"
                
            # Generate chart
            chart_path = "/app/charts/signal_chart.png"
            ta.plot_indicators(signals, save_path=chart_path)
            
            # Create message
            current_price = self.gold_monitor.get_current_price()
            message = (
                f"📊 XAU/USD Trading Signal: {signal_type}\n\n"
                f"💰 Current Price: ${current_price:.2f}\n"
                f"📈 RSI: {float(latest_signal['RSI']):.2f}\n"
                f"📉 MACD: {float(latest_signal['MACD']):.2f}\n\n"
            )
            
            if float(latest_signal['RSI']) > 70:
                message += "RSI indicates OVERBOUGHT conditions.\n"
            elif float(latest_signal['RSI']) < 30:
                message += "RSI indicates OVERSOLD conditions.\n"
                
            if float(latest_signal['MACD']) > float(latest_signal['MACD_Signal']):
                message += "MACD is BULLISH (MACD line above Signal line).\n"
            else:
                message += "MACD is BEARISH (MACD line below Signal line).\n"
                
            # Send message with chart
            with open(chart_path, 'rb') as chart:
                update.message.reply_photo(photo=chart, caption=message)
                
        except Exception as e:
            logger.error(f"Error in signal command: {e}")
            update.message.reply_text(f"Error generating signal: {str(e)}")
            
    def news_command(self, update, context):
        """Handle /news command"""
        try:
            update.message.reply_text("Fetching latest gold news...")
            
            # Fetch news
            news = self.news_monitor.fetch_all_news()
            
            if news is None or news.empty:
                update.message.reply_text("No gold-related news found.")
                return
                
            # Get latest news
            latest_news = self.news_monitor.get_latest_news(limit=5)
            
            # Create message
            message = "📰 Latest Gold News:\n\n"
            
            for i, (_, row) in enumerate(latest_news.iterrows()):
                impact = "🔴 High" if row['impact'] >= 0.8 else "🟠 Medium" if row['impact'] >= 0.6 else "🟡 Low"
                message += f"{i+1}. [{row['source']}] {row['title']}\n"
                message += f"   Impact: {impact} ({row['impact']:.2f})\n"
                message += f"   {row['url']}\n\n"
                
            update.message.reply_text(message)
                
        except Exception as e:
            logger.error(f"Error in news command: {e}")
            update.message.reply_text(f"Error fetching news: {str(e)}")
            
    def report_command(self, update, context):
        """Handle /report command"""
        try:
            update.message.reply_text("Generating EOD report...")
            
            # Generate EOD report
            report_data = self.notifier.generate_eod_report()
            
            if report_data is None:
                update.message.reply_text("Failed to generate EOD report.")
                return
                
            # Generate HTML report
            report_path = self.reporter.generate_eod_report(report_data)
            
            if report_path is None:
                update.message.reply_text("Failed to generate HTML report.")
                return
                
            # Format report message
            report_message = self.notifier.format_eod_report_message(report_data)
            
            # Send report message
            update.message.reply_text(report_message)
            
            # Send chart if available
            if 'chart_path' in report_data and os.path.exists(report_data['chart_path']):
                with open(report_data['chart_path'], 'rb') as chart:
                    update.message.reply_photo(photo=chart, caption="EOD Chart")
                    
        except Exception as e:
            logger.error(f"Error in report command: {e}")
            update.message.reply_text(f"Error generating report: {str(e)}")
            
    def settings_command(self, update, context):
        """Handle /settings command"""
        chat_id = str(update.effective_chat.id)
        
        # Find user
        user = None
        for u in self.users['users']:
            if str(u['chat_id']) == chat_id:
                user = u
                break
                
        if user is None:
            update.message.reply_text("You are not registered. Use /start to register.")
            return
            
        # Get current settings
        settings = user['settings']
        
        # Create message
        message = (
            "🔧 Notification Settings:\n\n"
            f"Price Alerts: {'✅ ON' if settings['price_alerts'] else '❌ OFF'}\n"
            f"Signal Alerts: {'✅ ON' if settings['signal_alerts'] else '❌ OFF'}\n"
            f"News Alerts: {'✅ ON' if settings['news_alerts'] else '❌ OFF'}\n"
            f"EOD Reports: {'✅ ON' if settings['eod_reports'] else '❌ OFF'}\n\n"
            "To change settings, reply with:\n"
            "price on/off\n"
            "signal on/off\n"
            "news on/off\n"
            "eod on/off"
        )
        
        update.message.reply_text(message)
        
    def handle_message(self, update, context):
        """Handle text messages"""
        chat_id = str(update.effective_chat.id)
        text = update.message.text.lower()
        
        # Find user
        user = None
        for u in self.users['users']:
            if str(u['chat_id']) == chat_id:
                user = u
                break
                
        if user is None:
            update.message.reply_text("You are not registered. Use /start to register.")
            return
            
        # Handle settings changes
        if text.startswith('price '):
            value = text.split(' ')[1].lower() == 'on'
            user['settings']['price_alerts'] = value
            self.save_users()
            update.message.reply_text(f"Price alerts turned {'ON' if value else 'OFF'}")
            
        elif text.startswith('signal '):
            value = text.split(' ')[1].lower() == 'on'
            user['settings']['signal_alerts'] = value
            self.save_users()
            update.message.reply_text(f"Signal alerts turned {'ON' if value else 'OFF'}")
            
        elif text.startswith('news '):
            value = text.split(' ')[1].lower() == 'on'
            user['settings']['news_alerts'] = value
            self.save_users()
            update.message.reply_text(f"News alerts turned {'ON' if value else 'OFF'}")
            
        elif text.startswith('eod '):
            value = text.split(' ')[1].lower() == 'on'
            user['settings']['eod_reports'] = value
            self.save_users()
            update.message.reply_text(f"EOD reports turned {'ON' if value else 'OFF'}")
            
        else:
            update.message.reply_text("I don't understand that command. Use /help to see available commands.")
            
    def error_handler(self, update, context):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
    def send_message_to_all(self, message, parse_mode=None):
        """Send message to all registered users"""
        for user in self.users['users']:
            try:
                self.bot.send_message(chat_id=user['chat_id'], text=message, parse_mode=parse_mode)
            except Exception as e:
                logger.error(f"Error sending message to {user['chat_id']}: {e}")
                
    def send_photo_to_all(self, photo_path, caption=None, parse_mode=None):
        """Send photo to all registered users"""
        for user in self.users['users']:
            try:
                with open(photo_path, 'rb') as photo:
                    self.bot.send_photo(chat_id=user['chat_id'], photo=photo, caption=caption, parse_mode=parse_mode)
            except Exception as e:
                logger.error(f"Error sending photo to {user['chat_id']}: {e}")
                
    def send_notification(self, notification):
        """Send notification to users based on their settings"""
        notification_type = notification['type']
        title = notification['title']
        message = notification['message']
        
        # Determine which users should receive this notification
        recipients = []
        for user in self.users['users']:
            settings = user['settings']
            
            if notification_type == 'price' and settings['price_alerts']:
                recipients.append(user)
            elif notification_type == 'signal' and settings['signal_alerts']:
                recipients.append(user)
            elif notification_type == 'news' and settings['news_alerts']:
                recipients.append(user)
                
        # Send notification to recipients
        full_message = f"🔔 {title}\n\n{message}"
        
        for user in recipients:
            try:
                self.bot.send_message(chat_id=user['chat_id'], text=full_message)
                
                # If there's a chart, send it
                if 'data' in notification and notification['data'] is not None:
                    if 'chart_path' in notification['data'] and notification['data']['chart_path'] is not None:
                        chart_path = notification['data']['chart_path']
                        if os.path.exists(chart_path):
                            with open(chart_path, 'rb') as chart:
                                self.bot.send_photo(chat_id=user['chat_id'], photo=chart)
            except Exception as e:
                logger.error(f"Error sending notification to {user['chat_id']}: {e}")
                
    def send_eod_report(self, report_data):
        """Send EOD report to users who have enabled it"""
        if report_data is None:
            logger.error("No report data to send")
            return
            
        # Generate HTML report
        report_path = self.reporter.generate_eod_report(report_data)
        
        if report_path is None:
            logger.error("Failed to generate HTML report")
            return
            
        # Format report message
        report_message = self.notifier.format_eod_report_message(report_data)
        
        # Determine which users should receive this report
        recipients = []
        for user in self.users['users']:
            if user['settings']['eod_reports']:
                recipients.append(user)
                
        # Send report to recipients
        for user in recipients:
            try:
                self.bot.send_message(chat_id=user['chat_id'], text=report_message)
                
                # Send chart if available
                if 'chart_path' in report_data and os.path.exists(report_data['chart_path']):
                    with open(report_data['chart_path'], 'rb') as chart:
                        self.bot.send_photo(chat_id=user['chat_id'], photo=chart, caption="EOD Chart")
            except Exception as e:
                logger.error(f"Error sending EOD report to {user['chat_id']}: {e}")
                
    def run_check_cycle(self):
        """Run a complete check cycle and send notifications"""
        logger.info("Running check cycle...")
        
        try:
            # Run check cycle
            notifications = self.notifier.run_check_cycle()
            
            if notifications:
                logger.info(f"Generated {len(notifications)} notifications")
                
                # Send notifications
                for notification in notifications:
                    self.send_notification(notification)
            else:
                logger.info("No notifications generated")
                
        except Exception as e:
            logger.error(f"Error in check cycle: {e}")
            
    def generate_and_send_eod_report(self):
        """Generate and send EOD report"""
        logger.info("Generating EOD report...")
        
        try:
            # Generate EOD report
            report_data = self.notifier.generate_eod_report()
            
            if report_data:
                logger.info("EOD report generated")
                
                # Send EOD report
                self.send_eod_report(report_data)
            else:
                logger.error("Failed to generate EOD report")
                
        except Exception as e:
            logger.error(f"Error generating EOD report: {e}")
            
    def start_polling(self):
        """Start polling for Telegram updates"""
        self.updater.start_polling()
        logger.info("Bot started polling")
        
    def stop_polling(self):
        """Stop polling for Telegram updates"""
        self.updater.stop()
        logger.info("Bot stopped polling")
        
    def run_monitoring(self, eod_report_time=EOD_REPORT_TIME):
        """
        Run continuous monitoring
        
        Parameters:
        eod_report_time (str): Time to generate EOD report (default: from environment)
        """
        logger.info(f"Starting continuous monitoring every {self.check_interval} seconds")
        logger.info(f"EOD report time: {eod_report_time}")
        
        # Start polling
        self.start_polling()
        
        last_eod_report_date = None
        
        try:
            while True:
                # Run check cycle
                self.run_check_cycle()
                
                # Check if it's time for EOD report
                current_time = datetime.now()
                current_time_str = current_time.strftime('%H:%M')
                current_date = current_time.date()
                
                if current_time_str >= eod_report_time and last_eod_report_date != current_date:
                    self.generate_and_send_eod_report()
                    last_eod_report_date = current_date
                    
                # Sleep until next check
                logger.info(f"Sleeping for {self.check_interval} seconds...")
                time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        except Exception as e:
            logger.error(f"Error in monitoring: {e}")
            # Implement retry mechanism
            logger.info("Restarting monitoring in 60 seconds...")
            time.sleep(60)
            self.run_monitoring(eod_report_time)
        finally:
            self.stop_polling()

def main():
    # Get Telegram bot token from environment variable
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)
            
    # Create TelegramNotifier
    notifier = TelegramNotifier(token=token, check_interval=CHECK_INTERVAL)
    
    # Run monitoring with retry mechanism
    max_retries = 5
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            notifier.run_monitoring(eod_report_time=EOD_REPORT_TIME)
            break
        except Exception as e:
            retry_count += 1
            logger.error(f"Error in main loop (retry {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                sleep_time = 60 * retry_count  # Exponential backoff
                logger.info(f"Restarting in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                logger.error("Maximum retries reached, exiting")
                sys.exit(1)

if __name__ == "__main__":
    main()
