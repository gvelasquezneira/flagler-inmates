import asyncio
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import re

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FlaglerInmateScraper:
    def __init__(self):
        self.base_url = "https://nwwebcad.fcpsn.org/NewWorld.InmateInquiry/FL0180000"
        self.db_path = "volusia_inmates.db"
        self.setup_database()
    
    def setup_database(self):
        """Create the database and table if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inmates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_num TEXT UNIQUE,
                inmate_id TEXT,
                last_name TEXT,
                first_name TEXT,
                middle_name TEXT,
                suffix TEXT,
                sex TEXT,
                race TEXT,
                booking_date TEXT,
                release_date TEXT,
                in_custody TEXT,
                photo_link TEXT,
                charges TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database setup complete")
    
    def get_date_range(self, days_back=2):
        """Get date range for scraping (yesterday to today by default)"""
        today = datetime.now()
        yesterday = today - timedelta(days=days_back)
        
        # Format dates as MM/DD/YYYY for the form
        from_date = yesterday.strftime("%m/%d/%Y")
        to_date = today.strftime("%m/%d/%Y")
        
        logger.info(f"Using date range: {from_date} to {to_date}")
        return from_date, to_date
    
    def parse_name(self, full_name):
        """Parse full name into components"""
        parts = full_name.split(', ')
        if len(parts) >= 2:
            last_name = parts[0].strip()
            remaining = parts[1].strip()
            
            # Split remaining by spaces
            name_parts = remaining.split()
            first_name = name_parts[0] if name_parts else ""
            middle_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            
            return last_name, first_name, middle_name, ""
        else:
            return full_name, "", "", ""
    
    async def scrape_inmate_list(self, page):
        """Scrape the main inmate list"""
        logger.info("Navigating to inmate search page")
        await page.goto(self.base_url)
        
        # Get date range
        from_date, to_date = self.get_date_range()
        
        # Fill in the date fields
        logger.info(f"Setting booking date range: {from_date} to {to_date}")
        await page.fill('#uxBookingFromDate', from_date)
        await page.fill('#uxBookingToDate', to_date)
        
        # Click search with date filters
        logger.info("Clicking search button with date filters")
        await page.click('input[type="submit"][value="Search"]')
        
        # Wait for results to load
        try:
            await page.wait_for_selector('.Results', timeout=10000)
        except:
            logger.error("No results found or page didn't load properly")
            return []
        
        inmates_data = []
        current_page = 1
        max_pages = 3  # Limit to 3 pages
        
        while current_page <= max_pages:
            logger.info(f"Scraping page {current_page}")
            
            # Check if we have results
            try:
                # Check for "no results" message or empty table
                no_results = await page.query_selector_all('.Results:has-text("No records found")')
                if no_results:
                    logger.info("No records found for the specified date range")
                    break
                
                # Get all inmate rows
                rows = await page.query_selector_all('tbody tr')
                
                if not rows:
                    logger.info("No inmate rows found on this page")
                    break
                
            except Exception as e:
                logger.error(f"Error checking for results: {e}")
                break
                
            for row in rows:
                try:
                    # Extract basic info from the list
                    name_cell = await row.query_selector('td.Name a')
                    subject_num_cell = await row.query_selector('td.SubjectNumber')
                    race_cell = await row.query_selector('td.Race')
                    gender_cell = await row.query_selector('td.Gender')
                    dob_cell = await row.query_selector('td.DateOfBirth')
                    height_cell = await row.query_selector('td.Height')
                    weight_cell = await row.query_selector('td.Weight')
                    
                    if name_cell:
                        name = await name_cell.inner_text()
                        detail_link = await name_cell.get_attribute('href')
                        subject_number = await subject_num_cell.inner_text() if subject_num_cell else ""
                        race = await race_cell.inner_text() if race_cell else ""
                        gender = await gender_cell.inner_text() if gender_cell else ""
                        dob = await dob_cell.inner_text() if dob_cell else ""
                        height = await height_cell.inner_text() if height_cell else ""
                        weight = await weight_cell.inner_text() if weight_cell else ""
                        
                        # Parse name
                        last_name, first_name, middle_name, suffix = self.parse_name(name)
                        
                        inmate_data = {
                            'name': name,
                            'detail_link': detail_link,
                            'subject_number': subject_number,
                            'last_name': last_name,
                            'first_name': first_name,
                            'middle_name': middle_name,
                            'suffix': suffix,
                            'race': race,
                            'gender': gender,
                            'dob': dob,
                            'height': height,
                            'weight': weight
                        }
                        
                        inmates_data.append(inmate_data)
                        
                except Exception as e:
                    logger.error(f"Error processing row: {e}")
                    continue
            
            # Check if there's a next page and we haven't reached the limit
            if current_page < max_pages:
                next_link = await page.query_selector('a.Next[href]')
                if next_link:
                    logger.info("Moving to next page")
                    await next_link.click()
                    await page.wait_for_selector('.Results')
                    current_page += 1
                else:
                    logger.info("No more pages found")
                    break
            else:
                logger.info(f"Reached maximum page limit of {max_pages}")
                break
        
        logger.info(f"Found {len(inmates_data)} inmates total from {current_page} pages")
        return inmates_data
    
    async def scrape_inmate_details(self, page, inmate_data):
        """Scrape individual inmate details"""
        detail_url = f"https://nwwebcad.fcpsn.org{inmate_data['detail_link']}"
        logger.info(f"Scraping details for {inmate_data['name']}")
        
        try:
            await page.goto(detail_url)
            await page.wait_for_selector('#Inmate_Detail')
            
            # Scrape demographic information
            demographics = {}
            demo_items = await page.query_selector_all('#DemographicInformation ul.FieldList li')
            
            for item in demo_items:
                label_elem = await item.query_selector('label')
                span_elem = await item.query_selector('span')
                
                if label_elem and span_elem:
                    label = await label_elem.inner_text()
                    value = await span_elem.inner_text()
                    demographics[label.lower().replace(' ', '_')] = value
            
            # Scrape booking history
            bookings = []
            booking_sections = await page.query_selector_all('#BookingHistory .Booking')
            
            for booking_section in booking_sections:
                booking_data = {}
                
                # Get booking number
                booking_header = await booking_section.query_selector('h3 span')
                if booking_header:
                    booking_data['booking_number'] = await booking_header.inner_text()
                
                # Get booking details
                booking_items = await booking_section.query_selector_all('ul.FieldList li')
                for item in booking_items:
                    label_elem = await item.query_selector('label')
                    span_elem = await item.query_selector('span')
                    
                    if label_elem and span_elem:
                        label = await label_elem.inner_text()
                        value = await span_elem.inner_text()
                        booking_data[label.lower().replace(' ', '_')] = value
                
                # Scrape charges for this booking
                charges = []
                charge_rows = await booking_section.query_selector_all('.BookingCharges tbody tr')
                
                for row in charge_rows:
                    charge = {}
                    cells = await row.query_selector_all('td')
                    
                    if len(cells) >= 13:
                        charge['seq_number'] = await cells[0].inner_text()
                        charge['charge_description'] = await cells[1].inner_text()
                        charge['counts'] = await cells[2].inner_text()
                        charge['offense_date'] = await cells[3].inner_text()
                        charge['docket_number'] = await cells[4].inner_text()
                        charge['sentence_date'] = await cells[5].inner_text()
                        charge['disposition'] = await cells[6].inner_text()
                        charge['disposition_date'] = await cells[7].inner_text()
                        charge['sentence_length'] = await cells[8].inner_text()
                        charge['crime_class'] = await cells[9].inner_text()
                        charge['arresting_agencies'] = await cells[10].inner_text()
                        charge['attempt_commit'] = await cells[11].inner_text()
                        charge['charge_bond'] = await cells[12].inner_text()
                        
                        charges.append(charge)
                
                booking_data['charges'] = charges
                bookings.append(booking_data)
            
            # Combine all data
            complete_data = {
                **inmate_data,
                'demographics': demographics,
                'bookings': bookings
            }
            
            return complete_data
            
        except Exception as e:
            logger.error(f"Error scraping details for {inmate_data['name']}: {e}")
            return None
    
    def save_to_database(self, inmates_data):
        """Save scraped data to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for inmate in inmates_data:
            try:
                # Determine most recent booking info
                booking_date = ""
                release_date = ""
                in_custody = "No"
                
                if inmate.get('bookings'):
                    latest_booking = inmate['bookings'][0]  # Assuming first is most recent
                    booking_date = latest_booking.get('booking_date', '')
                    release_date = latest_booking.get('release_date', '')
                    in_custody = "Yes" if not release_date else "No"
                
                # Prepare charges as JSON
                all_charges = []
                for booking in inmate.get('bookings', []):
                    all_charges.extend(booking.get('charges', []))
                
                charges_json = json.dumps(all_charges)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO inmates 
                    (booking_num, inmate_id, last_name, first_name, middle_name, suffix,
                     sex, race, booking_date, release_date, in_custody, photo_link, charges)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    inmate.get('bookings', [{}])[0].get('booking_number', '') if inmate.get('bookings') else '',
                    inmate.get('subject_number', ''),
                    inmate.get('last_name', ''),
                    inmate.get('first_name', ''),
                    inmate.get('middle_name', ''),
                    inmate.get('suffix', ''),
                    inmate.get('gender', ''),
                    inmate.get('race', ''),
                    booking_date,
                    release_date,
                    in_custody,
                    '',  # photo_link - not available in this system
                    charges_json
                ))
                
            except Exception as e:
                logger.error(f"Error saving {inmate.get('name', 'Unknown')}: {e}")
                continue
        
        conn.commit()
        conn.close()
        logger.info(f"Saved {len(inmates_data)} inmates to database")
    
    async def run(self, max_inmates=None, days_back=2):
        """Main scraping function"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                # Get list of all inmates
                inmates_list = await self.scrape_inmate_list(page)
                
                if not inmates_list:
                    logger.warning("No inmates found for the specified date range")
                    return
                
                if max_inmates:
                    inmates_list = inmates_list[:max_inmates]
                
                # Scrape details for each inmate
                detailed_inmates = []
                for i, inmate in enumerate(inmates_list):
                    logger.info(f"Processing inmate {i+1}/{len(inmates_list)}: {inmate['name']}")
                    
                    detailed_data = await self.scrape_inmate_details(page, inmate)
                    if detailed_data:
                        detailed_inmates.append(detailed_data)
                    
                    # Small delay to be respectful
                    await asyncio.sleep(1)
                
                # Save to database
                if detailed_inmates:
                    self.save_to_database(detailed_inmates)
                    logger.info("Scraping completed successfully")
                else:
                    logger.warning("No detailed inmate data was collected")
                
            except Exception as e:
                logger.error(f"Scraping failed: {e}")
            finally:
                await browser.close()

if __name__ == "__main__":
    scraper = FlaglerInmateScraper()
    asyncio.run(scraper.run(days_back=2))