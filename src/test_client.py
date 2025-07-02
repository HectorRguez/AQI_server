import requests
import json
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import seaborn as sns
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class AQITestClient:
    """Test client for AQI Flask server"""

    def __init__(self, base_url="http://localhost:5000"):
        self.base_url = base_url
        self.session = requests.Session()

        # Read the secret key from the environment
        self.api_key = os.environ.get("API_SECRET_KEY")

        # Ensure the API key is set before proceeding
        if not self.api_key:
            raise ValueError(
                "API_SECRET_KEY not found in environment. "
                "Please create a .env file with the key."
            )

        # Set the API key as a default header for all requests in this session
        self.session.headers.update({"X-API-Key": self.api_key})

        # Setup figures directory
        self.figures_dir = os.path.join(
            os.path.dirname(__file__), "figures"
        )
        os.makedirs(self.figures_dir, exist_ok=True)
        print(
            f"Figures will be saved to: {os.path.abspath(self.figures_dir)}"
        )

    def test_current_aqi(self):
        """Test current AQI endpoint for Beijing"""
        print("\n=== Testing Current AQI ===")

        test_cities = [(39.9042, 116.4074, "Beijing")]

        for lat, lon, city in test_cities:
            print(f"\n--- Testing {city} ---")
            # The API key header is now sent automatically by the session
            response = self.session.get(
                f"{self.base_url}/api/current",
                params={"lat": lat, "lon": lon},
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("list"):
                    aqi = data["list"][0]["main"]["aqi"]
                    pm25 = data["list"][0]["components"]["pm2_5"]
                    pm10 = data["list"][0]["components"]["pm10"]

                    print(f"✓ Current AQI: {aqi}")
                    print(f"  PM2.5: {pm25:.2f} μg/m³")
                    print(f"  PM10: {pm10:.2f} μg/m³")

                    self._plot_current_aqi(data, city)
            else:
                print(f"✗ Error: {response.status_code} - {response.text}")

    def test_forecast_aqi(self):
        """Test forecast AQI endpoint for Beijing"""
        print("\n=== Testing Forecast AQI ===")

        test_cities = [(39.9042, 116.4074, "Beijing")]

        for lat, lon, city in test_cities:
            print(f"\n--- Testing {city} Forecast ---")
            response = self.session.get(
                f"{self.base_url}/api/forecast",
                params={"lat": lat, "lon": lon},
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("list"):
                    print(f"✓ Forecast data points: {len(data['list'])}")
                    next_24h = data["list"][:8]
                    avg_aqi = (
                        sum(item["main"]["aqi"] for item in next_24h)
                        / len(next_24h)
                    )
                    print(f"  Next 24h average AQI: {avg_aqi:.1f}")
                    self._plot_forecast_aqi(data, city)
            else:
                print(f"✗ Error: {response.status_code} - {response.text}")

    def test_historical_aqi(self):
        """Test historical AQI endpoint for Beijing"""
        print("\n=== Testing Historical AQI ===")

        test_cities = [(39.9042, 116.4074, "Beijing")]

        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        for lat, lon, city in test_cities:
            print(f"\n--- Testing {city} Historical Data ---")
            response = self.session.get(
                f"{self.base_url}/api/historical",
                params={
                    "lat": lat,
                    "lon": lon,
                    "start": start_date.date().isoformat(),
                    "end": end_date.date().isoformat(),
                },
            )

            if response.status_code == 200:
                data = response.json()
                source = data.get("source", "unknown")
                print(f"✓ Data source: {source}")

                if "data" in data:
                    if isinstance(data["data"], list) and data["data"]:
                        print(f"  Data points: {len(data['data'])}")
                        self._plot_historical_aqi(data["data"], city)
                    elif (
                        isinstance(data["data"], dict)
                        and "list" in data["data"]
                    ):
                        print(f"  Data points: {len(data['data']['list'])}")
                        self._plot_historical_api_format(data["data"], city)
                    else:
                        print("  No data points available")
            else:
                print(f"✗ Error: {response.status_code} - {response.text}")

    def _plot_current_aqi(self, data, city_name):
        """Simple plot for current AQI data"""
        if not data.get("list"):
            return

        components = data["list"][0]["components"]
        pollutants = ["PM2.5", "PM10", "CO", "NO2", "SO2", "O3"]
        values = [
            components.get("pm2_5", 0),
            components.get("pm10", 0),
            components.get("co", 0) / 100,
            components.get("no2", 0),
            components.get("so2", 0),
            components.get("o3", 0),
        ]

        plt.figure(figsize=(10, 6))
        colors = ["red", "orange", "yellow", "green", "blue", "purple"]
        bars = plt.bar(pollutants, values, color=colors, alpha=0.7)

        for bar, value, pollutant in zip(bars, values, pollutants):
            height = bar.get_height()
            display_value = value * 100 if pollutant == "CO" else value
            plt.text(
                bar.get_x() + bar.get_width() / 2.0,
                height,
                f"{display_value:.1f}",
                ha="center",
                va="bottom",
            )

        plt.xlabel("Pollutants")
        plt.ylabel("Concentration (μg/m³)")
        plt.title(
            f'{city_name} - Current Air Quality (AQI: {data["list"][0]["main"]["aqi"]})'
        )
        plt.tight_layout()

        filepath = os.path.join(
            self.figures_dir, f"current_{city_name.lower()}.png"
        )
        plt.savefig(filepath)
        plt.close()
        print(f"  Saved: {os.path.basename(filepath)}")

    def _plot_forecast_aqi(self, data, city_name):
        """Simple plot for forecast AQI data"""
        if not data.get("list"):
            return

        timestamps = [
            datetime.fromtimestamp(item["dt"]) for item in data["list"]
        ]
        aqi_values = [item["main"]["aqi"] for item in data["list"]]
        pm25_values = [item["components"]["pm2_5"] for item in data["list"]]

        fig, ax1 = plt.subplots(figsize=(12, 6))

        color = "tab:blue"
        ax1.set_xlabel("Time")
        ax1.set_ylabel("AQI Value", color=color)
        ax1.plot(
            timestamps,
            aqi_values,
            color=color,
            linewidth=2,
            marker="o",
            markersize=4,
        )
        ax1.tick_params(axis="y", labelcolor=color)
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, 6)

        ax2 = ax1.twinx()
        color = "tab:red"
        ax2.set_ylabel("PM2.5 (μg/m³)", color=color)
        ax2.plot(
            timestamps,
            pm25_values,
            color=color,
            linewidth=2,
            linestyle="--",
            alpha=0.7,
        )
        ax2.tick_params(axis="y", labelcolor=color)

        plt.title(f"{city_name} - 4-Day Air Quality Forecast")
        plt.xticks(rotation=45)
        plt.tight_layout()

        filepath = os.path.join(
            self.figures_dir, f"forecast_{city_name.lower()}.png"
        )
        plt.savefig(filepath)
        plt.close()
        print(f"  Saved: {os.path.basename(filepath)}")

    def _plot_historical_aqi(self, data, city_name):
        """Simple plot for historical AQI data"""
        if not data:
            return

        df = pd.DataFrame(data)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")

        plt.figure(figsize=(12, 8))

        plt.subplot(2, 1, 1)
        plt.plot(df["datetime"], df["aqi"], "b-", linewidth=2, label="AQI")
        plt.ylabel("AQI Value")
        plt.title(f"{city_name} - 7-Day Historical Air Quality")
        plt.legend()
        plt.grid(True, alpha=0.3)

        plt.subplot(2, 1, 2)
        plt.plot(df["datetime"], df["pm2_5"], "r-", label="PM2.5", alpha=0.8)
        plt.plot(df["datetime"], df["pm10"], "g-", label="PM10", alpha=0.8)
        plt.xlabel("Date")
        plt.ylabel("PM Concentration (μg/m³)")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)

        plt.tight_layout()

        filepath = os.path.join(
            self.figures_dir, f"historical_{city_name.lower()}.png"
        )
        plt.savefig(filepath)
        plt.close()
        print(f"  Saved: {os.path.basename(filepath)}")

    def _plot_historical_api_format(self, data, city_name):
        """Handle API format historical data"""
        if not data.get("list"):
            return

        records = []
        for item in data["list"]:
            record = {
                "timestamp": item["dt"],
                "aqi": item["main"]["aqi"],
                **item["components"],
            }
            records.append(record)

        self._plot_historical_aqi(records, city_name)

    def run_all_tests(self):
        """Run all tests for Beijing"""
        print("=" * 50)
        print("AQI Server Test Suite - Beijing")
        print("=" * 50)

        try:
            response = self.session.get(f"{self.base_url}/api/health")
            if response.status_code == 200:
                health_data = response.json()
                print("✓ Server is healthy")
                print(
                    f"  Historical data: {health_data.get('historical_days', 'N/A')} days"
                )
                print(
                    f"  Database: {os.path.basename(health_data.get('database', 'N/A'))}"
                )
            else:
                print("✗ Server health check failed")
                return
        except Exception as e:
            print(f"✗ Cannot connect to server: {e}")
            print(
                "Make sure the Flask server is running on http://localhost:5000"
            )
            return

        try:
            response = self.session.get(f"{self.base_url}/api/info")
            if response.status_code == 200:
                info = response.json()
                print(
                    f"  Update interval: {info.get('update_interval_seconds', 'N/A')} seconds"
                )
        except:
            pass

        self.test_current_aqi()
        self.test_forecast_aqi()
        self.test_historical_aqi()

        print("\n" + "=" * 50)
        print("✓ All tests completed!")
        print(
            f"Generated plots saved to: {os.path.abspath(self.figures_dir)}"
        )
        print("  - current_beijing.png")
        print("  - forecast_beijing.png")
        print("  - historical_beijing.png")
        print("=" * 50)


if __name__ == "__main__":
    client = AQITestClient()
    client.run_all_tests()