import appdaemon.plugins.hass.hassapi as hass
from google.cloud import bigquery
from dotenv import load_dotenv
import pandas as pd
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
        # entity_id = os.getenv("TARGET_ENTITY_ID")
        # self.listen_state(self.backup_location, entity_id)

        # 2. 定期保存（例: 1時間ごと）
        eneity_ids = os.getenv("TARGET_ENTITY_IDS")
        self.entity_list = [e.strip() for e in eneity_ids.split(",") if e.strip()]

        # 毎日深夜 3:00 に実行
        self.run_daily(self.daily_batch, datetime(2026,1,1,3,0,0).time())

        # テスト用: 起動5秒後に実行
        self.run_in(self.daily_batch, 5)

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

    def daily_batch(self, kwargs):
        if not self.entity_list:
            return

        end_time = datetime.now(TZ_JST)
        start_time = end_time - timedelta(days=7)
        # 開始時刻は00:00:00に (都度その開始時刻で切り取られるため)
        start_time = start_time.replace(hour=0, minute=0, second=0)

        try:
            # 1. BigQueryから既存データを取得
            entities_str = ",".join([f"'{e}'" for e in self.entity_list])
            query = f"""
                SELECT CAST(datetime AS STRING) as datetime, entity_id
                FROM `{self.table_id}`
                WHERE datetime >= '{start_time.replace(tzinfo=None).isoformat()}'
                AND entity_id IN ({entities_str})
            """
            bq_df = self.client.query(query).to_dataframe()
            
            if not bq_df.empty:
                # BQからのデータを「秒単位」に固定して変換
                bq_df['datetime'] = pd.to_datetime(bq_df['datetime']).dt.floor('s')

            # 2. Home Assistantから履歴を取得
            history_data = self.get_history(entity_id=self.entity_list, start_time=start_time, end_time=end_time)

            # start_timeとの比較用に、タイムゾーンなし・ミリ秒なしのdatetimeオブジェクトを作成
            comparison_start = start_time.replace(tzinfo=None, microsecond=0)

            ha_records = []
            for entity_history in history_data:
                for state in entity_history:
                    # HAが生成する「開始時刻時点での状態」レコードを除外
                    # last_changed が start_time と秒単位まで一致する場合はスキップ
                    ts_utc = pd.to_datetime(state.get("last_changed"))
                    ts_jst_naive = ts_utc.astimezone(TZ_JST).replace(tzinfo=None, microsecond=0)
                    
                    if ts_jst_naive == comparison_start:
                        continue # 擬似レコードなので飛ばす

                    attr = state.get("attributes", {})
                    location = attr.get("location")
                    
                    if location and isinstance(location, (list, tuple)) and len(location) >= 2:
                        ha_records.append({
                            "datetime": ts_jst_naive,
                            "entity_id": state.get("entity_id"),
                            "latitude": location[0],
                            "longitude": location[1]
                        })

            ha_df = pd.DataFrame(ha_records)
            if ha_df.empty:
                return

            # HA側も念のため秒単位にフロア(念押し)
            ha_df['datetime'] = ha_df['datetime'].dt.floor('s')

            # 3. アンチジョインで差分抽出
            if bq_df.empty:
                delta_df = ha_df
            else:
                # merge前に両方の型を確実に一致させる
                merged = pd.merge(
                    ha_df, bq_df[['datetime', 'entity_id']], 
                    on=['datetime', 'entity_id'], 
                    how='left', 
                    indicator=True
                )
                delta_df = merged[merged['_merge'] == 'left_only'].drop(columns=['_merge'])

            # 4. インサート処理
            if not delta_df.empty:
                # 送信直前に文字列へ変換
                output_df = delta_df.copy()
                output_df['datetime'] = output_df['datetime'].dt.strftime('%Y-%m-%dT%H:%M:%S')
                rows_to_insert = output_df.to_dict(orient='records')
                
                errors = self.client.insert_rows_json(self.table_id, rows_to_insert)
                if errors == []:
                    self.log(f"Synced {len(rows_to_insert)} new records.")
                else:
                    self.error(f"BQ Insert Error: {errors}")
            else:
                self.log(f"new record is none.")

        except Exception as e:
            self.error(f"Sync failed: {e}")