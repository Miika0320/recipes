Recipe App Setup
================
1. Install dependencies:
   pip install -r requirements.txt

2. Create a Firebase project and get your Web config.
   Paste it into firebase_config.json.

3. To import sample recipes:
   - Import recipes_import.json into Firebase Realtime Database via the Firebase Console.

4. Run the app:
   python main.py

Options:
   1. Bulk scrape from URLs
   2. Add a manual recipe
   3. Export a recipe to PDF

All recipes are stored in Firebase and can be edited there.
