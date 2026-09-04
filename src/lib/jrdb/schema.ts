import type Database from "better-sqlite3";

export function createSchema(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS races (
      race_id TEXT PRIMARY KEY,
      race_date TEXT NOT NULL,
      venue_code TEXT NOT NULL,
      venue_name TEXT NOT NULL,
      race_number INTEGER NOT NULL,
      race_name TEXT,
      distance INTEGER NOT NULL,
      surface TEXT NOT NULL,
      track_condition TEXT,
      course_direction TEXT,
      head_count INTEGER,
      start_time TEXT,
      grade TEXT,
      race_class TEXT,
      weather TEXT,
      created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS entries (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      race_id TEXT NOT NULL /* REFERENCES races(race_id) */,
      horse_number INTEGER NOT NULL,
      gate_number INTEGER,
      horse_id TEXT,
      horse_name TEXT NOT NULL,
      jockey_name TEXT NOT NULL,
      jockey_code TEXT,
      trainer_name TEXT NOT NULL,
      trainer_code TEXT,
      carried_weight REAL NOT NULL,
      horse_weight INTEGER,
      horse_weight_diff INTEGER,
      age TEXT,
      sex TEXT,
      odds_win REAL,
      popularity INTEGER,
      UNIQUE(race_id, horse_number)
    );

    CREATE TABLE IF NOT EXISTS results (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      race_id TEXT NOT NULL /* REFERENCES races(race_id) */,
      horse_number INTEGER NOT NULL,
      horse_id TEXT,
      finish_position INTEGER,
      finish_time REAL,
      margin TEXT,
      last_3f REAL,
      corner_positions TEXT,
      jockey_name TEXT,
      carried_weight REAL,
      horse_weight INTEGER,
      horse_weight_diff INTEGER,
      win_odds REAL,
      popularity INTEGER,
      prize_money REAL,
      UNIQUE(race_id, horse_number)
    );

    CREATE TABLE IF NOT EXISTS horses (
      horse_id TEXT PRIMARY KEY,
      horse_name TEXT NOT NULL,
      birth_year INTEGER,
      sex TEXT,
      coat_color TEXT,
      sire TEXT,
      dam TEXT,
      dam_sire TEXT,
      breeder TEXT,
      owner TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS odds (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      race_id TEXT NOT NULL /* REFERENCES races(race_id) */,
      bet_type TEXT NOT NULL,
      combination TEXT NOT NULL,
      odds REAL NOT NULL,
      updated_at TEXT DEFAULT (datetime('now')),
      UNIQUE(race_id, bet_type, combination)
    );

    CREATE TABLE IF NOT EXISTS lap_times (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      race_id TEXT NOT NULL /* REFERENCES races(race_id) */,
      section_number INTEGER NOT NULL,
      section_time REAL NOT NULL,
      UNIQUE(race_id, section_number)
    );

    CREATE TABLE IF NOT EXISTS import_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      file_name TEXT NOT NULL,
      file_type TEXT NOT NULL,
      record_count INTEGER,
      status TEXT NOT NULL,
      error_message TEXT,
      imported_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS paper_trades (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      race_id TEXT NOT NULL,
      race_date TEXT NOT NULL,
      bet_type TEXT NOT NULL,
      combination TEXT NOT NULL,
      amount INTEGER NOT NULL,
      odds REAL NOT NULL,
      ev REAL,
      ai_score_json TEXT,
      result TEXT DEFAULT 'pending',
      payout REAL DEFAULT 0,
      created_at TEXT DEFAULT (datetime('now')),
      settled_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_paper_race ON paper_trades(race_id);
    CREATE INDEX IF NOT EXISTS idx_paper_date ON paper_trades(race_date);
    CREATE INDEX IF NOT EXISTS idx_paper_result ON paper_trades(result);

    CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date);
    CREATE INDEX IF NOT EXISTS idx_races_venue ON races(venue_code);
    CREATE INDEX IF NOT EXISTS idx_entries_race ON entries(race_id);
    CREATE INDEX IF NOT EXISTS idx_entries_horse ON entries(horse_id);
    CREATE INDEX IF NOT EXISTS idx_results_race ON results(race_id);
    CREATE INDEX IF NOT EXISTS idx_results_horse ON results(horse_id);
    CREATE INDEX IF NOT EXISTS idx_odds_race ON odds(race_id);
    CREATE INDEX IF NOT EXISTS idx_lap_race ON lap_times(race_id);
  `);
}
