import os
import json
import time
import sqlite3
import requests
import threading
import datetime
import random
from flask import Flask, jsonify, request
from flask_cors import CORS
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple
from functools import wraps
import logging

# Load environment
from dotenv import load_dotenv
load_dotenv() 

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration and API key safety
API_KEY = os.environ.get('OPENWEATHER_API_KEY', 'your_api_key_here')
API_SECRET_KEY = os.environ.get('API_SECRET_KEY')
BASE_URL = "http://api.openweathermap.org/data/2.5/air_pollution"
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if the API key is present and correct
        if request.headers.get('X-API-Key') and request.headers.get('X-API-Key') == API_SECRET_KEY:
            return f(*args, **kwargs)
        else:
            # If key is missing or incorrect, return an error
            return jsonify({"error": "API key is missing or invalid"}), 401
    return decorated_function


# Updated paths for data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)  # Create data directory if it doesn't exist

DB_NAME = os.path.join(DATA_DIR, "aqi_data.db")
FAKE_DATA_FILE = os.path.join(DATA_DIR, "fake_aqi_data.txt")
HISTORICAL_DAYS = 30  # Number of days of historical data

# Database setup
def init_db():
    """Initialize the SQLite database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS aqi_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            aqi INTEGER NOT NULL,
            pm2_5 REAL,
            pm10 REAL,
            co REAL,
            no REAL,
            no2 REAL,
            o3 REAL,
            so2 REAL,
            nh3 REAL,
            location_name TEXT,
            source TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_timestamp_location 
        ON aqi_data(timestamp, latitude, longitude)
    ''')
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at: {DB_NAME}")

@contextmanager
def get_db():
    """Database connection context manager"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

class FakeDataGenerator:
    """Generate fake AQI data for testing/fallback"""
    
    @staticmethod
    def generate_fake_data(lat: float, lon: float, timestamp: Optional[int] = None) -> Dict:
        """Generate realistic fake AQI data"""
        if timestamp is None:
            timestamp = int(time.time())
        
        # Generate correlated pollutant values
        base_pollution = random.uniform(0.3, 0.8)
        
        # Add time-based variation (pollution tends to be higher during day)
        hour = datetime.datetime.fromtimestamp(timestamp).hour
        time_factor = 1.0 + 0.3 * abs(hour - 12) / 12  # Peak at noon
        
        # Add some variation based on location (simulate different pollution levels)
        if abs(lat - 39.9042) < 1 and abs(lon - 116.4074) < 1:  # Beijing area
            base_pollution *= 1.5  # Higher pollution
        elif abs(lat - 31.2304) < 1 and abs(lon - 121.4737) < 1:  # Shanghai area
            base_pollution *= 1.3
        
        base_pollution *= time_factor
        
        return {
            "coord": [lat, lon],
            "list": [{
                "dt": timestamp,
                "main": {
                    "aqi": min(5, max(1, int(1 + base_pollution * 4)))
                },
                "components": {
                    "co": 200 + random.uniform(-50, 300) * base_pollution,
                    "no": random.uniform(0, 10) * base_pollution,
                    "no2": random.uniform(0, 50) * base_pollution,
                    "o3": 60 + random.uniform(-20, 40) * base_pollution,
                    "so2": random.uniform(0, 20) * base_pollution,
                    "pm2_5": random.uniform(0, 75) * base_pollution,
                    "pm10": random.uniform(0, 150) * base_pollution,
                    "nh3": random.uniform(0, 10) * base_pollution
                }
            }]
        }
    
    @staticmethod
    def generate_bulk_historical_data(
        lat: float, lon: float, start_time: int, end_time: int
    ) -> Dict:
        """Generate historical fake data for a time range in bulk"""
        historical_list = []
        current_time = start_time
        while current_time <= end_time:
            fake_data = FakeDataGenerator.generate_fake_data(
                lat, lon, current_time
            )
            historical_list.extend(fake_data["list"])
            current_time += 3600
        logger.info(
            f"Generated {len(historical_list)} historical data points for location ({lat}, {lon})"
        )
        result = {"coord": [lat, lon], "list": historical_list}
        result["source"] = "Synthetic Fallback"  # <-- Add source
        return result
    
    @staticmethod
    def save_fake_data_to_file():
        """Save fake data samples to file"""
        fake_samples = []
        
        # Updated locations with Beijing and Shanghai
        locations = [
            (40.7128, -74.0060, "New York"),
            (51.5074, -0.1278, "London"),
            (35.6762, 139.6503, "Tokyo"),
            (39.9042, 116.4074, "Beijing"),
            (31.2304, 121.4737, "Shanghai")
        ]
        
        for lat, lon, city in locations:
            for hours_ago in range(0, 48, 3):
                timestamp = int(time.time()) - (hours_ago * 3600)
                fake_data = FakeDataGenerator.generate_fake_data(lat, lon, timestamp)
                fake_data["location_name"] = city
                fake_samples.append(fake_data)
        
        with open(FAKE_DATA_FILE, 'w') as f:
            json.dump(fake_samples, f, indent=2)
        
        logger.info(f"Saved {len(fake_samples)} fake data samples to {FAKE_DATA_FILE}")

class AQIService:
    """Service class for AQI data operations"""

    def check_api_availability(self) -> str:
        """Performs a quick check to see if the OpenWeatherMap API is available."""
        try:
            # Use a known location for a quick, lightweight check
            lat, lon = 40.7128, -74.0060  # New York
            url = f"{BASE_URL}?lat={lat}&lon={lon}&appid={API_KEY}"
            # Use a short timeout for a quick check
            response = requests.get(url, timeout=5)
            response.raise_for_status()  # Will raise an error on 4xx or 5xx
            return "available"
        except Exception as e:
            logger.warning(f"API availability check failed: {e}")
            return "unavailable"
    
    def fetch_current_aqi(self, lat: float, lon: float) -> Optional[Dict]:
        """Fetch current AQI data from API"""
        try:
            url = f"{BASE_URL}?lat={lat}&lon={lon}&appid={API_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            data["source"] = "OpenWeatherMap API"  # <-- Add source
            return data
        except Exception as e:
            logger.error(f"API error: {e}")
            return self._get_fallback_data(lat, lon)

    def fetch_forecast_aqi(self, lat: float, lon: float) -> Optional[Dict]:
        """Fetch AQI forecast data from API"""
        try:
            url = f"{BASE_URL}/forecast?lat={lat}&lon={lon}&appid={API_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            data["source"] = "OpenWeatherMap API"  # <-- Add source
            return data
        except Exception as e:
            logger.error(f"Forecast API error: {e}")
            return self._generate_forecast_fallback(lat, lon)

    def fetch_historical_aqi(
        self, lat: float, lon: float, start: int, end: int
    ) -> Optional[Dict]:
        """Fetch historical AQI data from API with immediate fallback to bulk generation"""
        try:
            url = f"{BASE_URL}/history?lat={lat}&lon={lon}&start={start}&end={end}&appid={API_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            data["source"] = "OpenWeatherMap API"  # <-- Add source
            return data
        except Exception as e:
            logger.error(f"Historical API error: {e}")
            logger.info(
                f"API failed, generating bulk historical data for ({lat}, {lon})"
            )
            return FakeDataGenerator.generate_bulk_historical_data(
                lat, lon, start, end
            )

    def _get_fallback_data(self, lat: float, lon: float) -> Dict:
        """Get fallback data from file or generate new"""
        try:
            location_name = self._get_location_name(lat, lon)
            if os.path.exists(FAKE_DATA_FILE):
                with open(FAKE_DATA_FILE, "r") as f:
                    fake_data = json.load(f)
                    for item in fake_data:
                        if (
                            abs(item["coord"][0] - lat) < 1
                            and abs(item["coord"][1] - lon) < 1
                        ):
                            result = item.copy()
                            if location_name:
                                result["location_name"] = location_name
                            result["source"] = "Synthetic Fallback"  # <-- Add source
                            return result
            result = FakeDataGenerator.generate_fake_data(lat, lon)
            if location_name:
                result["location_name"] = location_name
            result["source"] = "Synthetic Fallback"  # <-- Add source
            return result
        except Exception as e:
            logger.error(f"Fallback data error: {e}")
            result = FakeDataGenerator.generate_fake_data(lat, lon)
            result["source"] = "Synthetic Fallback"  # <-- Add source
            return result

    def _generate_forecast_fallback(self, lat: float, lon: float) -> Dict:
        """Generate fake forecast data"""
        forecast_data = {"coord": [lat, lon], "list": []}
        current_time = int(time.time())
        for hours_ahead in range(0, 96, 3):
            timestamp = current_time + (hours_ahead * 3600)
            fake_item = FakeDataGenerator.generate_fake_data(lat, lon, timestamp)
            forecast_data["list"].append(fake_item["list"][0])
        forecast_data["source"] = "Synthetic Fallback"  # <-- Add source
        return forecast_data
    
    def _get_location_name(self, lat: float, lon: float) -> Optional[str]:
        """Get location name based on coordinates"""
        locations = [
            (40.7128, -74.0060, "New York"),
            (51.5074, -0.1278, "London"),
            (35.6762, 139.6503, "Tokyo"),
            (39.9042, 116.4074, "Beijing"),
            (31.2304, 121.4737, "Shanghai")
        ]
        
        for loc_lat, loc_lon, name in locations:
            if abs(lat - loc_lat) < 0.1 and abs(lon - loc_lon) < 0.1:
                return name
        return None
    
    def save_to_database(self, data: Dict, location_name: Optional[str] = None):
        """Save AQI data to database"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                print(f"Saving data for location: {location_name}")
                
                # If location_name is in the data dict, use it
                if isinstance(data, dict) and "location_name" in data:
                    location_name = data["location_name"]
                raw_coord = data.get("coord", {})
                if isinstance(raw_coord, dict):
                    lat, lon = raw_coord.get("lat"), raw_coord.get("lon")
                else:
                    lat, lon = raw_coord[0], raw_coord[1]

                saved_count = 0
                for item in data.get("list", []):
                    cursor.execute('''
                        INSERT INTO aqi_data 
                        (timestamp, latitude, longitude, aqi, pm2_5, pm10, co, no, no2, o3, so2, nh3, location_name, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        item["dt"],
                        lat,
                        lon,
                        item["main"]["aqi"],
                        item["components"].get("pm2_5"),
                        item["components"].get("pm10"),
                        item["components"].get("co"),
                        item["components"].get("no"),
                        item["components"].get("no2"),
                        item["components"].get("o3"),
                        item["components"].get("so2"),
                        item["components"].get("nh3"),
                        location_name,
                        data.get("source", "unknown")
                    ))
                    saved_count += 1
                
                conn.commit()
                logger.info(f"Saved {saved_count} records to database")
        except Exception as e:
            logger.error(f"Database save error: {e}")
    
    def get_historical_from_db(self, lat: float, lon: float, start_time: int, end_time: int) -> List[Dict]:
        """Retrieve historical data from database"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT * FROM aqi_data
                    WHERE latitude BETWEEN ? AND ?
                    AND longitude BETWEEN ? AND ?
                    AND timestamp BETWEEN ? AND ?
                    ORDER BY timestamp
                ''', (lat - 0.1, lat + 0.1, lon - 0.1, lon + 0.1, start_time, end_time))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Database query error: {e}")
            return []

def populate_initial_historical_data():
    """Populate database with initial historical data for all locations"""
    service = AQIService()
    
    locations = [
        (40.7128, -74.0060, "New York"),
        (51.5074, -0.1278, "London"),
        (35.6762, 139.6503, "Tokyo"),
        (39.9042, 116.4074, "Beijing"),
        (31.2304, 121.4737, "Shanghai")
    ]
    
    # Generate data for the last HISTORICAL_DAYS days
    end_time = int(time.time())
    start_time = end_time - (HISTORICAL_DAYS * 24 * 3600)
    
    logger.info(f"Populating historical data for the last {HISTORICAL_DAYS} days")
    
    for lat, lon, name in locations:
        # Check if we already have sufficient data for this location
        existing_data = service.get_historical_from_db(lat, lon, start_time, end_time)
        
        # We expect approximately 24 * HISTORICAL_DAYS data points (hourly data)
        expected_data_points = 24 * HISTORICAL_DAYS
        
        if len(existing_data) < expected_data_points * 0.8:  # If we have less than 80% of expected data
            logger.info(f"Populating historical data for {name} (existing: {len(existing_data)}, expected: ~{expected_data_points})")
            
            # Try API first, but it will likely fail and generate bulk fake data
            historical_data = service.fetch_historical_aqi(lat, lon, start_time, end_time)
            if historical_data:
                historical_data["location_name"] = name
                service.save_to_database(historical_data, name)
        else:
            logger.info(f"Sufficient historical data already exists for {name} ({len(existing_data)} points)")


# Flask Routes
@app.route('/api/current', methods=['GET'])
@require_api_key
def get_current_aqi():
    """Get current AQI data"""
    service = AQIService()
    
    # Get location from parameters
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    if not (lat and lon):
        return jsonify({"error": "Location required (lat/lon)"}), 400
    
    # Fetch current data
    data = service.fetch_current_aqi(lat, lon)
    if data:
        # Also save to database
        service.save_to_database(data)
        return jsonify(data)
    
    return jsonify({"error": "Failed to fetch AQI data"}), 500

@app.route('/api/forecast', methods=['GET'])
@require_api_key
def get_forecast_aqi():
    """Get AQI forecast data"""
    service = AQIService()
    
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    if not (lat and lon):
        return jsonify({"error": "Coordinates required"}), 400
    
    data = service.fetch_forecast_aqi(lat, lon)
    if data:
        return jsonify(data)
    
    return jsonify({"error": "Failed to fetch forecast data"}), 500

@app.route('/api/historical', methods=['GET'])
@require_api_key
def get_historical_aqi():
    """Get historical AQI data"""
    service = AQIService()
    
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    if not all([lat, lon, start_date, end_date]):
        return jsonify({"error": "lat, lon, start, and end parameters required"}), 400
    
    try:
        start_ts = int(datetime.datetime.fromisoformat(start_date).timestamp())
        end_ts = int(datetime.datetime.fromisoformat(end_date).timestamp())
        
        # First, try to get from the local database
        db_data = service.get_historical_from_db(lat, lon, start_ts, end_ts)
        
        if db_data:
            # If found in DB, wrap it in the expected format and set the source
            return jsonify({
                "coord": [lat, lon],
                "list": db_data,
                "source": "Local Database"
            })
        
        # If not in DB, fetch from API (which has its own fallback)
        api_data = service.fetch_historical_aqi(lat, lon, start_ts, end_ts)
        if api_data:
            # The source is already in api_data, just save and return
            service.save_to_database(api_data)
            return jsonify(api_data)
        
        return jsonify({"error": "No historical data available"}), 404
        
    except Exception as e:
        logger.error("Error in /api/historical", exc_info=True)
        return jsonify({"error": str(e)}), 400

@app.route('/api/health', methods=['GET'])
@require_api_key
def health_check():
    """Health check endpoint"""
    service = AQIService()
    api_status = service.check_api_availability()

    return jsonify({
        "status": "healthy", 
        "timestamp": int(time.time()),
        "database": DB_NAME,
        "openweather_api_status": api_status,
        "historical_days": HISTORICAL_DAYS,
        "data_directory": DATA_DIR,
    })

def initialize_app():
    """Initialize the application"""
    logger.info(f"Starting AQI Flask Server...")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Historical data period: {HISTORICAL_DAYS} days")
    
    # Initialize database
    init_db()
    
    # Generate fake data file if it doesn't exist
    if not os.path.exists(FAKE_DATA_FILE):
        FakeDataGenerator.save_fake_data_to_file()
    
    # Populate initial historical data
    populate_initial_historical_data()
    
    logger.info("Application initialized successfully")

# Initialize the application when the module is imported
initialize_app()

# This block is now only for running in development mode directly
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)