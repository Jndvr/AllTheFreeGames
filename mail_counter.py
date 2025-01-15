import os
import json
from datetime import datetime
import logging

class MailCounter:
    def __init__(self, log_file="mail_counter.json"):
        # Ensure static_data directory exists
        self.static_data_dir = "static_data"
        if not os.path.exists(self.static_data_dir):
            os.makedirs(self.static_data_dir)
            
        self.log_file = os.path.join(self.static_data_dir, log_file)
        self.monthly_limit = 3000
        self.current_count = 0
        self.last_reset = None
        self.load_counter()
    
    def load_counter(self):
        """Load the counter from the JSON file or create if doesn't exist"""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                    self.current_count = data.get('count', 0)
                    self.last_reset = datetime.fromisoformat(data.get('last_reset', datetime.now().isoformat()))
            else:
                self.reset_counter()
        except Exception as e:
            logging.error(f"Error loading mail counter: {e}")
            self.reset_counter()

    def save_counter(self):
        """Save the current counter state to the JSON file"""
        try:
            with open(self.log_file, 'w') as f:
                json.dump({
                    'count': self.current_count,
                    'last_reset': self.last_reset.isoformat()
                }, f)
        except Exception as e:
            logging.error(f"Error saving mail counter: {e}")

    def reset_counter(self):
        """Reset the counter and update last reset time"""
        self.current_count = 0
        self.last_reset = datetime.now()
        self.save_counter()
        logging.info("Mail counter reset successfully")

    def check_monthly_reset(self):
        """Check if we need to reset the counter for a new month"""
        current_date = datetime.now()
        if self.last_reset.month != current_date.month or self.last_reset.year != current_date.year:
            self.reset_counter()
            return True
        return False

    def increment(self, count=1):
        """
        Check how many emails can be sent from the requested count.
        Returns tuple (can_send_count, success)
        - can_send_count: number of emails that can be sent (0 to count)
        - success: True if all requested emails can be sent, False if only partial or none
        """
        self.check_monthly_reset()
        
        remaining = self.monthly_limit - self.current_count
        can_send = min(count, remaining)
        
        if can_send <= 0:
            logging.warning(f"Monthly email limit ({self.monthly_limit}) reached. Current: {self.current_count}")
            return (0, False)
        
        if can_send < count:
            logging.warning(f"Can only send {can_send} out of {count} emails. Monthly limit: {self.monthly_limit}, Current: {self.current_count}")
            self.current_count += can_send
            self.save_counter()
            return (can_send, False)
            
        self.current_count += count
        self.save_counter()
        logging.info(f"Mail counter incremented by {count}. New total: {self.current_count}")
        return (count, True)

    def get_remaining(self):
        """Get remaining emails for the month"""
        self.check_monthly_reset()
        return max(0, self.monthly_limit - self.current_count)