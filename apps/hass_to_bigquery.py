import appdaemon.plugins.hass.hassapi as hass
from google.cloud import bigquery
from dotenv import load_dotenv
import os
from datetime import datetime, timezone, timedelta

# JSTのタイムゾーンを定義 (+9時間)
TZ_JST = timezone(timedelta(hours=+9), 'JST')

class HassToBigQuery(hass.Hass):

    def initialize(self):
        load_dotenv()

        # サービスアカウントキー
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.client = bigquery.Client()
        self.table_id = os.getenv("BIGQUERY_TABLE_PATH")

        # 1. リアルタイム保存（位置情報が変わるたび）
        entity_id = os.getenv("TARGET_ENTITY_ID")
        self.listen_state(self.backup_location, entity_id)

        # 2. 定期保存（例: 1時間ごと）
        # self.run_every(self.periodic_backup, "now", 60 * 60)

    def backup_location(self, entity, attribute, old, new, kwargs):
        try:
            # 緯度・経度属性を取得
            state = self.get_state(entity, attribute="all")
            lat = state['attributes']['location'][0]
            lon = state['attributes']['location'][1]

            if lat and lon:
                self.send_to_bq(entity, lat, lon)
        except Exception as e:
            self.error(e)

    def send_to_bq(self, entity_id, lat, lon):
        datetime_now = datetime.now(TZ_JST)
        rows_to_insert = [{
            "datetime": datetime_now.replace(tzinfo=None).isoformat(timespec='seconds'), 
            "entity_id": entity_id,
            "latitude": lat,
            "longitude": lon
        }]
        
        errors = self.client.insert_rows_json(self.table_id, rows_to_insert)
        if errors == []:
            self.log(f"Success: Saved {entity_id} to BigQuery.")
        else:
            self.error(f"Error inserting rows: {errors}")

    def periodic_backup(self, kwargs):
        self.log("Running periodic backup check...")
        # 必要なエンティティをループして保存する処理などを記述
