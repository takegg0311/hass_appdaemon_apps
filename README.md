# AppDaemon Apps

Home Assistant 上の [AppDaemon](https://appdaemon.readthedocs.io/) で動かす自作アプリを管理するリポジトリです。

## 構成

```
.
├── appdaemon.yaml          # AppDaemon 本体設定（タイムゾーン・HASS プラグインなど）
├── apps/
│   ├── apps.yaml           # アプリの登録定義
│   ├── hello.py            # サンプルアプリ
│   └── hass_to_bigquery.py # 位置情報の BigQuery 同期
├── dashboards/
│   └── Hello.dash          # HADashboard サンプル
└── .env.sample             # 環境変数のテンプレート
```

## 前提

- Home Assistant + AppDaemon（アドオン想定）
- Google Cloud サービスアカウント（BigQuery 書き込み権限）
- Python 依存（AppDaemon 実行環境側）:
  - `google-cloud-bigquery`
  - `python-dotenv`
  - `pandas`

## セットアップ

1. `.env.sample` を `.env` にコピーする
2. 以下を設定する

| 変数名 | 説明 |
| --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS` | サービスアカウント JSON のパス（コンテナ内パス。`/config/` は addon_configs 直下） |
| `BIGQUERY_TABLE_PATH` | 書き込み先テーブル ID（例: `project.dataset.table`） |
| `TARGET_ENTITY_IDS` | 同期対象の entity ID（カンマ区切り） |

3. サービスアカウント JSON を配置し、`.env` のパスと一致させる（`*.json` は `.gitignore` 対象）
4. `apps/apps.yaml` でアプリが有効になっていることを確認する

```yaml
hello_world:
  module: hello
  class: HelloWorld
bigquery_backup:
  module: hass_to_bigquery
  class: HassToBigQuery
```

## アプリ一覧

### `HassToBigQuery`（`apps/hass_to_bigquery.py`）

Home Assistant の entity 履歴から位置情報（`attributes.location`）を取得し、BigQuery へ差分同期する。

**動作概要**

- 毎日 2:00（JST）に日次バッチを実行
- 起動から 5 秒後にも 1 回実行（動作確認用）
- 対象: `TARGET_ENTITY_IDS` に列挙した entity
- 期間: 直近 7 日分（開始日 00:00:00 から現在まで）
- BigQuery 既存データと HA 履歴を突き合わせ、未登録分のみ `insert_rows_json` で挿入

**保存スキーマ（想定）**

| カラム | 内容 |
| --- | --- |
| `datetime` | 記録時刻（JST、秒精度、`YYYY-MM-DDTHH:MM:SS`） |
| `entity_id` | Home Assistant の entity ID |
| `latitude` | 緯度 |
| `longitude` | 経度 |
| `address` | 住所 (Geocoded Location) |

**補足**

- HA 履歴の「開始時刻時点の擬似レコード」（`last_changed` が取得開始時刻と一致）は除外する
- リアルタイム保存用の `backup_location` / `listen_state` は実装済みだが、現状はコメントアウト

## AppDaemon 設定メモ

`appdaemon.yaml` では次を設定している。

- タイムゾーン: `Asia/Tokyo`
- HASS プラグイン: Supervisor トークン（`SUPERVISOR_TOKEN`）経由
- HTTP: `http://0.0.0.0:5050`
