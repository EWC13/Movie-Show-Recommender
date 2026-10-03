# Movie-Show-Recommender

This repository hosts a project I made with the assistance of Claude Code. A mood based move/TV recommender web application with two different kinds of search utilizing AI (Claude) or key word search. The application allows for users to select the streaming service they want to search for movies on based on the top 10 streaming services from TMDB.

## Setup

1. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Get API keys:
   - **TMDB**: create a free account at https://www.themoviedb.org/, then go to
     Settings -> API to get an API key (v3 auth) or read access token (v4 auth).
   - **Anthropic**: get an API key from https://console.anthropic.com/ (separate
     from any Claude Code login — this key is used by the running app to call
     Claude on each request).

3. Copy `.env.example` to `.env` and fill in both keys:
   ```
   copy .env.example .env
   ```

4. Run the dev server:
   ```
   uvicorn app.main:app --reload
   ```

5. Open http://localhost:8000 in a browser.

API docs (Swagger UI) are available at http://localhost:8000/docs for manually
testing `POST /api/recommend` directly.

## Tests

```
pytest
```

## Notes

- Streaming availability defaults to the US region.
- If you select zero streaming services, the app searches across all known
  providers instead of filtering by provider.
