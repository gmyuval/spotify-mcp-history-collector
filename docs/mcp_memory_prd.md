# PRD — Persistent Taste Memory + Playlist Ledger for music.praxiscode.dev (MCP Extension)

**Document version:** 1.0  
**Owner:** Product / Platform  
**Audience:** Engineering (human or AI), Ops  
**Scope:** Add a persistent “memory” subsystem to the existing MCP server powering Spotify Listening Analyst.

---

## 1) Summary

Implement a **persistent memory subsystem** inside the `music.praxiscode.dev` MCP server that stores, per `user_id`:

1) **Taste Profile** (durable preferences + rules + constraints)  
2) **Playlist Ledger** (every playlist created/edited by the assistant; includes track IDs and mutations)

Expose MCP tools under a `memory.*` namespace to:
- read/update taste profile
- append preference events (explicit feedback)
- log playlist creation and edits (add/remove/reorder/meta)
- reconstruct playlist state even when Spotify read-back is blocked
- search across memory
- export/delete user data

> Practical motivation: Spotify read-back may fail or be forbidden in some environments, so the ledger is the canonical record of what the assistant did.

---

## 2) Problem Statement

Today, cross-session continuity is limited:
- LLM context is ephemeral across chats/sessions.
- Spotify playlist retrieval may be blocked (e.g., 403 Forbidden), making it hard to remember what was in a playlist we created.
- Without a durable system-of-record, we can’t reliably remember:
  - stable curation rules (e.g., “avoid over-weighting a single artist”)
  - previous playlists and their contents
  - “taste evolution” over time

---

## 3) Goals and Non-Goals

### Goals
- **G1:** Persist user taste profile and explicit rules.
- **G2:** Persist created/edited playlists with **track IDs** and change history.
- **G3:** Provide reliable reconstruction of playlist contents without Spotify read-back.
- **G4:** Provide assistant-friendly, typed MCP tool interfaces (schemas, errors, idempotency).
- **G5:** Provide user control: export + delete.

### Non-Goals (Phase 1)
- Full recommender model or audio-feature pipeline.
- Storing full raw play logs (already handled by the history store).
- Complex multi-tenant RBAC beyond strict `user_id` isolation.

---

## 4) Personas / Users
- **Primary:** End user with Spotify account (`user_id`)
- **Operator:** Dev/Ops managing the MCP server
- **Agent:** LLM tool-caller using `memory.*` tools

---

## 5) Key Use Cases (User Stories)

### Taste memory
1) “Remember I like upbeat symphonic/power metal, with contemplative breaks.”
2) “Remember: don’t overweight one artist in a playlist.”
3) “Keep pop as an accent, not the main course.”

### Playlist ledger
4) “List playlists you created for me and what’s in them.”
5) “Make a v2 of that playlist with more new tracks.”
6) “Undo the last change.”
7) “Export/delete everything you stored.”

### Analysis enablement
8) “What’s newly in rotation vs long-term staples?”
9) “What rules keep recurring in my feedback?”

---

## 6) Requirements

### 6.1 Functional Requirements (MVP)
**FR1 — Taste Profile CRUD**
- Create/retrieve profile by `user_id`
- Update profile via patch/merge
- Append explicit preference events with timestamp

**FR2 — Playlist Record + Ledger**
- Log playlist creation: metadata + ordered `track_ids`
- Log playlist mutations: add/remove/reorder/update_meta
- Reconstruct playlist contents from snapshots + events

**FR3 — Search**
- Keyword search across:
  - playlist names/descriptions/notes/tags
  - preference events + profile notes

**FR4 — Export / Delete**
- Export all stored data for a `user_id` as JSON
- Delete all stored data for a `user_id` (hard delete MVP)

**FR5 — Ergonomics**
- Consistent tool response envelope:
  - `success` boolean
  - `result` OR `error`

### 6.2 Non-Functional Requirements
- **Security:** strict user isolation, auth required for writes
- **Durability:** ACID for writes
- **Performance:** reconstruct < 200ms typical using snapshots
- **Observability:** tool latency/error metrics; structured logs

---

## 7) Data Model (Recommended)

### Entities
**TasteProfile**
- `user_id` (PK)
- `profile_json` (JSON/JSONB)
- `version` (int)
- `updated_at` (timestamp)

**PreferenceEvent** (append-only)
- `event_id` (UUID)
- `user_id`
- `timestamp`
- `source` (`user` | `assistant` | `inferred`)
- `type` (`like` | `dislike` | `rule` | `feedback` | `note`)
- `payload_json` (JSON)

**Playlist**
- `playlist_id` (PK, Spotify playlist ID string)
- `user_id`
- `name`, `description`
- `created_at`
- `intent_tags` (array / JSON)
- `seed_context` (JSON)
- `latest_snapshot_id` (FK)
- `updated_at`

**PlaylistSnapshot**
- `snapshot_id` (UUID)
- `playlist_id`
- `created_at`
- `track_ids` (ordered array / JSON)
- `source` (`create` | `periodic` | `manual`)

**PlaylistEvent** (append-only ledger)
- `event_id` (UUID)
- `playlist_id`, `user_id`
- `timestamp`
- `type` (`ADD_TRACKS` | `REMOVE_TRACKS` | `REORDER` | `UPDATE_META`)
- `payload_json` (JSON)
- `client_event_id` (optional UUID for idempotency)

### Storage choice
- MVP: SQLite (fast to ship)
- Recommended: Postgres + JSONB (concurrency, future growth)
- Phase 2 optional: semantic search with vectors

---

## 8) MCP Tool Surface

### Tool list
- `memory.get_profile`
- `memory.update_profile`
- `memory.append_preference_event`
- `memory.log_playlist_create`
- `memory.log_playlist_mutation`
- `memory.get_playlists`
- `memory.get_playlist`
- `memory.reconstruct_playlist`
- `memory.search`
- `memory.export_user_data`
- `memory.delete_user_data`

---

# 9) JSON Schemas (Tool Inputs/Outputs)

## 9.1 Shared Definitions

### 9.1.1 Standard response envelope (all tools)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.tool.response.schema.json",
  "title": "MemoryToolResponse",
  "type": "object",
  "additionalProperties": false,
  "required": ["success"],
  "properties": {
    "success": { "type": "boolean" },
    "result": { "type": ["object", "array", "string", "number", "boolean", "null"] },
    "error": { "$ref": "#/$defs/ErrorObject" }
  },
  "$defs": {
    "ErrorObject": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "message"],
      "properties": {
        "code": {
          "type": "string",
          "enum": [
            "INVALID_ARGUMENT",
            "UNAUTHORIZED",
            "FORBIDDEN",
            "NOT_FOUND",
            "CONFLICT",
            "RATE_LIMITED",
            "INTERNAL",
            "DB_ERROR"
          ]
        },
        "message": { "type": "string" },
        "details": { "type": ["object", "array", "string", "null"] }
      }
    }
  }
}
```

### 9.1.2 Common primitives
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.common.schema.json",
  "$defs": {
    "UserId": { "type": "integer", "minimum": 1 },
    "SpotifyPlaylistId": { "type": "string", "minLength": 10, "maxLength": 80 },
    "SpotifyTrackId": { "type": "string", "minLength": 10, "maxLength": 80 },
    "ISODateTime": { "type": "string", "format": "date-time" },
    "JSONStringObject": { "type": "object" }
  }
}
```

---

## 9.2 `memory.get_profile`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.get_profile.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" }
  }
}
```

### Output `result` schema (on success)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.get_profile.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "profile", "version", "updated_at"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "profile": { "type": "object" },
    "version": { "type": "integer", "minimum": 0 },
    "updated_at": {
      "anyOf": [
        { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
        { "type": "null" }
      ]
    }
  }
}
```

---

## 9.3 `memory.update_profile`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.update_profile.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "patch"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "patch": { "type": "object" },
    "reason": { "type": "string", "minLength": 1 },
    "source": { "type": "string", "enum": ["user", "assistant", "inferred"], "default": "assistant" },
    "create_if_missing": { "type": "boolean", "default": true }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.update_profile.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "profile", "version", "updated_at"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "profile": { "type": "object" },
    "version": { "type": "integer", "minimum": 1 },
    "updated_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" }
  }
}
```

---

## 9.4 `memory.append_preference_event`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.append_preference_event.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "type", "payload"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "type": { "type": "string", "enum": ["like", "dislike", "rule", "feedback", "note"] },
    "payload": { "type": "object" },
    "source": { "type": "string", "enum": ["user", "assistant", "inferred"], "default": "assistant" },
    "timestamp": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.append_preference_event.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["event_id", "user_id", "timestamp"],
  "properties": {
    "event_id": { "type": "string", "format": "uuid" },
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "timestamp": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" }
  }
}
```

---

## 9.5 `memory.log_playlist_create`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.log_playlist_create.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "playlist_id", "name", "track_ids"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "name": { "type": "string", "minLength": 1, "maxLength": 200 },
    "description": { "type": "string", "maxLength": 2000 },
    "track_ids": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "memory.common.schema.json#/$defs/SpotifyTrackId" }
    },
    "intent_tags": { "type": "array", "items": { "type": "string" }, "default": [] },
    "seed_context": { "type": "object", "default": {} },
    "created_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "idempotency_key": { "type": "string", "minLength": 8 }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.log_playlist_create.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["playlist_id", "snapshot_id", "created_at", "stored_track_count"],
  "properties": {
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "snapshot_id": { "type": "string", "format": "uuid" },
    "created_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "stored_track_count": { "type": "integer", "minimum": 1 }
  }
}
```

---

## 9.6 `memory.log_playlist_mutation`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.log_playlist_mutation.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "playlist_id", "type", "payload"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "type": { "type": "string", "enum": ["ADD_TRACKS", "REMOVE_TRACKS", "REORDER", "UPDATE_META"] },
    "payload": { "type": "object" },
    "timestamp": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "client_event_id": { "type": "string", "format": "uuid" }
  },
  "allOf": [
    {
      "if": { "properties": { "type": { "const": "ADD_TRACKS" } } },
      "then": {
        "properties": {
          "payload": {
            "type": "object",
            "additionalProperties": false,
            "required": ["track_ids"],
            "properties": {
              "track_ids": {
                "type": "array",
                "minItems": 1,
                "items": { "$ref": "memory.common.schema.json#/$defs/SpotifyTrackId" }
              },
              "insert_at": { "type": "integer", "minimum": 0 },
              "positions": { "type": "array", "items": { "type": "integer", "minimum": 0 } }
            }
          }
        }
      }
    },
    {
      "if": { "properties": { "type": { "const": "REMOVE_TRACKS" } } },
      "then": {
        "properties": {
          "payload": {
            "type": "object",
            "additionalProperties": false,
            "required": ["track_ids"],
            "properties": {
              "track_ids": {
                "type": "array",
                "minItems": 1,
                "items": { "$ref": "memory.common.schema.json#/$defs/SpotifyTrackId" }
              }
            }
          }
        }
      }
    },
    {
      "if": { "properties": { "type": { "const": "REORDER" } } },
      "then": {
        "properties": {
          "payload": {
            "type": "object",
            "additionalProperties": false,
            "required": ["track_ids"],
            "properties": {
              "track_ids": {
                "type": "array",
                "minItems": 1,
                "items": { "$ref": "memory.common.schema.json#/$defs/SpotifyTrackId" }
              }
            }
          }
        }
      }
    },
    {
      "if": { "properties": { "type": { "const": "UPDATE_META" } } },
      "then": {
        "properties": {
          "payload": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "name": { "type": "string", "minLength": 1, "maxLength": 200 },
              "description": { "type": "string", "maxLength": 2000 },
              "intent_tags": { "type": "array", "items": { "type": "string" } }
            }
          }
        }
      }
    }
  ]
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.log_playlist_mutation.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["event_id", "playlist_id", "timestamp"],
  "properties": {
    "event_id": { "type": "string", "format": "uuid" },
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "timestamp": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "new_snapshot_id": { "type": ["string", "null"], "format": "uuid" }
  }
}
```

---

## 9.7 `memory.get_playlists`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.get_playlists.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "limit": { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 },
    "cursor": { "type": "string" }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.get_playlists.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["items", "next_cursor"],
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["playlist_id", "name", "created_at", "updated_at", "intent_tags"],
        "properties": {
          "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
          "name": { "type": "string" },
          "created_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
          "updated_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
          "intent_tags": { "type": "array", "items": { "type": "string" } },
          "track_count": { "type": "integer", "minimum": 0 }
        }
      }
    },
    "next_cursor": { "type": ["string", "null"] }
  }
}
```

---

## 9.8 `memory.get_playlist`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.get_playlist.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "playlist_id"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "include_events_limit": { "type": "integer", "minimum": 0, "maximum": 500, "default": 50 }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.get_playlist.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["playlist", "latest_snapshot", "recent_events"],
  "properties": {
    "playlist": {
      "type": "object",
      "additionalProperties": false,
      "required": ["playlist_id", "user_id", "name", "created_at", "updated_at", "intent_tags"],
      "properties": {
        "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
        "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
        "name": { "type": "string" },
        "description": { "type": "string" },
        "created_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
        "updated_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
        "intent_tags": { "type": "array", "items": { "type": "string" } },
        "seed_context": { "type": "object" }
      }
    },
    "latest_snapshot": {
      "type": "object",
      "additionalProperties": false,
      "required": ["snapshot_id", "created_at", "track_ids"],
      "properties": {
        "snapshot_id": { "type": "string", "format": "uuid" },
        "created_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
        "track_ids": {
          "type": "array",
          "items": { "$ref": "memory.common.schema.json#/$defs/SpotifyTrackId" }
        }
      }
    },
    "recent_events": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["event_id", "timestamp", "type", "payload"],
        "properties": {
          "event_id": { "type": "string", "format": "uuid" },
          "timestamp": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
          "type": { "type": "string" },
          "payload": { "type": "object" }
        }
      }
    }
  }
}
```

---

## 9.9 `memory.reconstruct_playlist`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.reconstruct_playlist.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "playlist_id"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "at_time": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.reconstruct_playlist.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["playlist_id", "as_of", "track_ids"],
  "properties": {
    "playlist_id": { "$ref": "memory.common.schema.json#/$defs/SpotifyPlaylistId" },
    "as_of": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "track_ids": {
      "type": "array",
      "items": { "$ref": "memory.common.schema.json#/$defs/SpotifyTrackId" }
    },
    "reconstruction": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "used_snapshot_id": { "type": ["string", "null"], "format": "uuid" },
        "applied_event_count": { "type": "integer", "minimum": 0 }
      }
    }
  }
}
```

---

## 9.10 `memory.search`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.search.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "query"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "query": { "type": "string", "minLength": 1, "maxLength": 500 },
    "limit": { "type": "integer", "minimum": 1, "maximum": 200, "default": 25 }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.search.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["results"],
  "properties": {
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["kind", "id", "score", "snippet"],
        "properties": {
          "kind": { "type": "string", "enum": ["playlist", "preference_event", "profile"] },
          "id": { "type": "string" },
          "score": { "type": "number" },
          "snippet": { "type": "string" },
          "metadata": { "type": "object" }
        }
      }
    }
  }
}
```

---

## 9.11 `memory.export_user_data`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.export_user_data.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.export_user_data.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "exported_at", "data"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "exported_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "data": { "type": "object" }
  }
}
```

---

## 9.12 `memory.delete_user_data`

### Input schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.delete_user_data.input.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "confirm"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "confirm": { "type": "boolean", "const": true }
  }
}
```

### Output `result` schema
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "memory.delete_user_data.result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["user_id", "deleted_at", "deleted"],
  "properties": {
    "user_id": { "$ref": "memory.common.schema.json#/$defs/UserId" },
    "deleted_at": { "$ref": "memory.common.schema.json#/$defs/ISODateTime" },
    "deleted": { "type": "boolean", "const": true }
  }
}
```

---

# 10) Tool-Calling Playbook (Assistant/Agent Behavior)

This is the “when to call what” guide to ensure memory is always correct, resilient to Spotify failures, and aligned with the user’s preferences.

## 10.1 Session bootstrap
**On every new session / conversation start:**
1) `ops.list_users`
2) If exactly one user: pick it; else ask user to choose.
3) `memory.get_profile(user_id)`
4) (Optional) `memory.get_playlists(user_id, limit=10)`
   - If user references “the playlist you made last time”, search or list to find the relevant `playlist_id`.

## 10.2 When user states a preference or gives feedback
**Trigger phrases:** “I like…”, “I don’t like…”, “remember…”, “too much of…”, “more/less…”, “keep it upbeat…”, “avoid X…”

Actions:
1) `memory.append_preference_event(user_id, type=rule|feedback|like|dislike, payload={...}, source="user")`
   - Include the user’s wording in `payload.raw_text`
2) `memory.update_profile(user_id, patch={...}, reason="User feedback: ...", source="user")`
   - Patch should update relevant fields like:
     - `playlist_rules.max_tracks_per_artist`
     - `energy_preferences`
     - `avoid`
     - `core_genres` / `secondary_vibes`

**Rule of thumb:** events capture *what was said*, profile captures *the normalized durable rule*.

## 10.3 Creating a new playlist (canonical workflow)
1) Run listening analysis tools as needed (e.g., `history.taste_summary`, `history.top_tracks`, etc.)
2) Generate candidate track IDs via `spotify.search` / other catalog tools.
3) Create playlist: `spotify.create_playlist`
4) Add tracks: `spotify.add_tracks`
5) Log to memory **immediately**:
   - `memory.log_playlist_create` with:
     - exact ordered `track_ids` you added
     - `intent_tags` (e.g., `["upbeat","breathers","symphonic metal"]`)
     - `seed_context` including:
       - time window (e.g., `days=60`)
       - top artists/tracks used as inspiration
       - constraints applied (duration target, max artist weighting)

**Important:** Do not rely on `spotify.get_playlist` as the system of record.
Memory is the truth.

## 10.4 Editing a playlist (adds/removes/rebalance)
For each Spotify mutation, log a corresponding memory mutation:

### Add tracks
1) `spotify.add_tracks(playlist_id, track_ids=[...])`
2) `memory.log_playlist_mutation(type="ADD_TRACKS", payload={track_ids:[...], insert_at?:n})`

### Remove tracks
1) `spotify.remove_tracks(playlist_id, track_ids=[...])`
2) `memory.log_playlist_mutation(type="REMOVE_TRACKS", payload={track_ids:[...]})`

### Reorder (if implemented)
1) Spotify reorder call (if supported in your tools)
2) `memory.log_playlist_mutation(type="REORDER", payload={track_ids:[full_order]})`

### Update name/description/tags
1) `spotify.update_playlist(...)`
2) `memory.log_playlist_mutation(type="UPDATE_META", payload={name?:..., description?:..., intent_tags?:[...]})`

## 10.5 Guardrails: artist over-weighting
Whenever generating or expanding playlists:
1) Read rule from profile:
   - e.g., `playlist_rules.max_tracks_per_artist` (default 3)
2) While selecting tracks:
   - cap tracks per artist
   - if user wants exceptions (e.g., “make it Nightwish-heavy”), log that feedback as an event and adjust temporarily

## 10.6 If Spotify read-back fails (403 / missing scopes)
- Do **not** attempt to “sync by reading Spotify”.
- Use:
  - `memory.get_playlist` or `memory.reconstruct_playlist`
  - for “what’s currently in it”, reconstruct from memory
- If you suspect out-of-band edits (user manually edited on Spotify):
  - Provide a “resync” user flow (Phase 2):
    - user exports playlist track list or provides playlist snapshot
    - tool `memory.log_playlist_snapshot_manual` (optional future tool)

## 10.7 Snapshots & compaction policy
To keep reconstruction fast:
- Create a snapshot:
  - at create
  - every **N=10** mutations (configurable)
- `memory.log_playlist_mutation` may return `new_snapshot_id` when compaction triggers.

## 10.8 “Find that playlist from before”
If user references a past playlist by vibe/name:
1) `memory.search(query="breathers upbeat metal")`
2) If a playlist result returns, `memory.get_playlist` to confirm details
3) Use ledger tracks as “seed set” for v2 creation

---

# 11) Seed Taste Profile Example (for this user)
Suggested initial normalized patch:

```json
{
  "core_genres": ["symphonic metal", "power metal", "melodic metal"],
  "secondary_vibes": ["hooky pop"],
  "energy_preferences": {
    "default": "upbeat/anthemic",
    "contemplative_breaks": true,
    "break_placement": "mid-playlist"
  },
  "playlist_rules": {
    "max_tracks_per_artist": 3,
    "arc": "drive → breather → drive",
    "target_duration_minutes": { "min": 90, "max": 180 }
  },
  "avoid": ["over-weighting a single artist in one playlist"]
}
```

---

# 12) Acceptance Criteria (MVP)
- Creating a playlist logs a durable record containing ordered `track_ids`.
- Editing a playlist logs mutations that allow accurate reconstruction.
- User preferences persist across sessions via `memory.get_profile`.
- Export returns all stored objects; delete removes all stored objects.
- No cross-user reads/writes possible.

---

# 13) Notes for Engineering
- Prefer Postgres + JSONB for longevity; SQLite acceptable for MVP.
- Implement idempotency for `log_playlist_create` and `log_playlist_mutation` (via `idempotency_key` / `client_event_id`).
- Validate schemas server-side; reject unknown fields (`additionalProperties:false`) to keep compatibility tight.
- Maintain structured logs: tool name, user_id, playlist_id, request_id, latency, success.

