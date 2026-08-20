# Room Database & Storage Migration Protocol

Strict rules for modifying Room entities, DAOs, schema versions, and preferences in Rashaqa Android.

---

## 1. Zero Data Loss Policy
Rashaqa has millions of active users and version codes over 900.
- ❌ **NEVER** use `fallbackToDestructiveMigration()` in production database builders.
- ❌ **NEVER** modify a table structure, column name, or index without an explicit `Migration(startVersion, endVersion)` object.

---

## 2. Safe Schema Modification Protocol
When adding or modifying an `@Entity`:
1. **Increment Database Version**:
   - Update `version = X` in `@Database(entities = [...], version = X)` in `AppDatabase.kt`.
2. **Write Explicit Migration**:
   ```kotlin
   val MIGRATION_X_Y = object : Migration(X, Y) {
       override fun migrate(db: SupportSQLiteDatabase) {
           db.execSQL("ALTER TABLE user_steps ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0")
       }
   }
   ```
3. **Register Migration**:
   - Add `addMigrations(MIGRATION_X_Y)` to the Room database builder in `DatabaseModule.kt`.
4. **Unit-Test Migration**:
   - Verify migration with `MigrationTestHelper` before delivering changes.

---

## 3. DataStore & EncryptedSharedPreferences
- **`EncryptedSharedPreferences`**:
  - Used for sensitive credentials, auth tokens, and security flags via `MasterKey` (`androidx.security:security-crypto`).
  - Never log decrypted auth tokens or store them in plaintext SharedPreferences.
- **`DataStore Preferences`**:
  - Prefer for asynchronous, reactive settings streams (`Flow<Preferences>`).
  - Read with `.data.catch { emit(emptyPreferences()) }` to recover a corrupt preferences file. That is framework recovery, not a dummy business fallback (`null`/`0` fake success).

---

## 4. Review Guard Checklist for Database
- If any `@Database` file or one of its entity classes is in the working tree:
  1. Did the integer `version` increment vs HEAD?
  2. Is `Migration(old, new)` present and passed to `addMigrations(...)`?
  3. Are nullability (`NOT NULL` vs `NULL`) and default values aligned with Kotlin types?
  4. Was `fallbackToDestructiveMigration()` removed for that schema change?
- `python .agents/scripts/preflight_check.py` runs this gate (`room_guard.py`). It maps `@Database` entity class names to any changed Kotlin type in the working tree (not filename stems). Anonymous `object : Migration(x, y)` still counts; `addMigrations(...)` must be present on a version bump.
