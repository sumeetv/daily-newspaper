import asyncio
import logging
import os
import pickle
from datetime import datetime

import aiohttp
import yaml
import jinja2
import feedparser
from todoist_api_python.api import TodoistAPI
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

class DailyNewspaper:
    def __init__(self, config_path="config.yaml"):
        self.logger = logging.getLogger(__name__)
        self.load_config(config_path)
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates")
        )
        
    def load_config(self, config_path):
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
            
    async def get_weather(self):
        """Fetch weather data from configured API"""
        async with aiohttp.ClientSession() as session:
            url = f"https://api.weatherapi.com/v1/forecast.json"
            params = {
                'key': self.config['weather_api_key'],
                'q': self.config['location'],
                'days': 1
            }
            async with session.get(url, params=params) as response:
                return await response.json()

    async def get_tasks(self):
        """Fetch Todoist tasks"""
        api = TodoistAPI(self.config['todoist_token'])
        try:
            tasks = api.get_tasks(filter="today | overdue")
            return tasks
        except Exception as e:
            self.logger.error(f"Error fetching Todoist tasks: {e}")
            return []

    def get_google_credentials(self):
        """Handle Google Calendar OAuth2 flow"""
        SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
        creds = None
        
        # The file token.pickle stores the user's access and refresh tokens
        if os.path.exists('secrets/token.pickle'):
            with open('secrets/token.pickle', 'rb') as token:
                creds = pickle.load(token)
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Manual authentication flow
                print("\nPlease follow these steps to authenticate with Google Calendar:")
                print("1. Go to this URL in your browser:")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.config['google_credentials_path'], 
                    SCOPES,
                    redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # This is key for manual auth
                )
                auth_url, _ = flow.authorization_url(prompt='consent')
                print(f"\n{auth_url}\n")
                print("2. Log in and grant access")
                print("3. Copy the authorization code and paste it below")
                code = input("Enter the authorization code: ")
                flow.fetch_token(code=code)
                creds = flow.credentials

            # Save the credentials for the next run
            with open('secrets/token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        
        return creds

    async def get_calendar_events(self):
        """Fetch Google Calendar events"""
        try:
            creds = self.get_google_credentials()
            service = build('calendar', 'v3', credentials=creds)
            
            now = datetime.utcnow().isoformat() + 'Z'
            today_end = datetime.utcnow().replace(hour=23, minute=59).isoformat() + 'Z'
            
            events_result = service.events().list(
                calendarId='primary',
                timeMin=now,
                timeMax=today_end,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return events_result.get('items', [])
        except Exception as e:
            self.logger.error(f"Error fetching calendar events: {e}")
            return []
        
        return events_result.get('items', [])

    async def get_news(self):
        """Fetch news from RSS feeds"""
        news_items = []
        for feed_url in self.config['rss_feeds']:
            try:
                feed = feedparser.parse(feed_url)
                news_items.extend(feed.entries[:5])  # Get top 5 stories from each feed
            except Exception as e:
                self.logger.error(f"Error fetching RSS feed {feed_url}: {e}")
        return news_items

    def generate_markdown(self, data):
        """Generate markdown from collected data"""
        template = self.template_env.get_template('newspaper.md.j2')
        return template.render(**data)

    async def generate_newspaper(self):
        """Main function to generate the daily newspaper"""
        try:
            # Gather all data concurrently
            weather, tasks, events, news = await asyncio.gather(
                self.get_weather(),
                self.get_tasks(),
                self.get_calendar_events(),
                self.get_news()
            )

            # Compile all data
            data = {
                'date': datetime.now().strftime("%A, %B %d, %Y"),
                'weather': weather,
                'tasks': tasks,
                'events': events,
                'news': news
            }

            # Generate markdown
            markdown = self.generate_markdown(data)

            # Save to file
            output_path = f"newspapers/{datetime.now().strftime('%Y-%m-%d')}.md"
            with open(output_path, 'w') as f:
                f.write(markdown)

            self.logger.info(f"Daily newspaper generated successfully: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"Error generating newspaper: {e}")
            raise

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run the newspaper generator
    newspaper = DailyNewspaper()
    asyncio.run(newspaper.generate_newspaper())