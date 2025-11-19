import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from recipe_scrapers import scrape_me
import pyrebase
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Frame,
    PageTemplate,
    BaseDocTemplate,
    FrameBreak,
    Table,
    TableStyle
)
from reportlab.lib import colors
from reportlab.pdfgen import canvas
import io
import os
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle, FrameBreak, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

# Try registering Baskerville font (you can place baskerville.ttf in your project folder)
try:
    pdfmetrics.registerFont(TTFont('Baskerville', 'baskerville.ttf'))
    base_font = 'Baskerville'
except:
    base_font = 'Times-Roman'  # Fallback if not found

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="RecipeTitle", fontName=base_font, fontSize=16, leading=18, alignment=1))
styles.add(ParagraphStyle(name="RecipeCategory", fontName=base_font, fontSize=10, leading=12, textColor=colors.grey))
styles.add(ParagraphStyle(name="RecipeText", fontName=base_font, fontSize=10, leading=12))


app = Flask(__name__)
app.secret_key = "thisisasecret"


# Firebase setup
with open("firebase_config.json") as f:
    firebase_config = json.load(f)

firebase = pyrebase.initialize_app(firebase_config)
db = firebase.database()

# ------------------ Helpers ------------------
def flatten_recipe(recipe_data):
    """Flatten nested dicts from Firebase if needed."""
    if isinstance(recipe_data, dict) and "ingredients" not in recipe_data and len(recipe_data) == 1:
        return list(recipe_data.values())[0]
    return recipe_data

def export_recipe_pdf(recipe):
    """Generate PDF for a single recipe."""
    pdf_file = f"{recipe['title']}.pdf"
    doc = SimpleDocTemplate(pdf_file, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{recipe['title']}</b>", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Category:</b> {recipe['category']}", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Ingredients:</b>", styles["Heading3"]))
    for ing in recipe["ingredients"]:
        story.append(Paragraph(f"- {ing}", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Instructions:</b>", styles["Heading3"]))
    story.append(Paragraph(recipe["instructions"], styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Source:</b> {recipe['source']}", styles["Italic"]))

    doc.build(story)
    return pdf_file

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Admin login required.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ------------------ Routes ------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            flash("Logged in successfully.")
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password.")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for("index"))


@app.route("/delete_recipe/<rid>", methods=["POST"])
@admin_required
def delete_recipe(rid):
    try:
        # 1. Check if the recipe key exists (Diagnostic Step)
        recipe_check = db.child("recipes").child(rid).get()
        
        if recipe_check.val() is None:
            # If the recipe is not found at the given path
            flash(f"Deletion failed: Recipe ID '{rid}' was not found.", "error")
            return redirect(url_for("view_recipes")) 
        
        # 2. If it exists, proceed with deletion
        db.child("recipes").child(rid).remove() 
        flash("Recipe deleted successfully.", "success")
        
    except Exception as e:
        flash(f"Critical error during deletion: {e}", "error")
        
    return redirect(url_for("view_recipes"))

# ------------------ Add Manual ------------------
@app.route("/add_manual", methods=["GET", "POST"])
def add_manual():
    if request.method == "POST":
        title = request.form.get("title")
        ingredients = [i.strip() for i in request.form.get("ingredients").split(",")]
        instructions = request.form.get("instructions")
        category = request.form.get("category")
        source = request.form.get("source")

        db.child("recipes").push({
            "title": title,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "source": source
        })
        return redirect(url_for("view_recipes"))

    return render_template("add_manual.html")

# ------------------ Add from URL ------------------
@app.route("/add_url", methods=["GET", "POST"])
def add_url():
    if request.method == "POST":
        urls = [u.strip() for u in request.form.get("urls").split(",")]
        category = request.form.get("category")
        for url in urls:
            try:
                scraper = scrape_me(url)
                db.child("recipes").push({
                    "title": scraper.title(),
                    "ingredients": scraper.ingredients(),
                    "instructions": scraper.instructions(),
                    "category": category,
                    "source": url
                })
            except Exception as e:
                print(f"Error scraping {url}: {e}")
        return redirect(url_for("view_recipes"))

    return render_template("add_url.html")

# ------------------ Upload JSON ------------------
@app.route("/upload_json", methods=["GET", "POST"])
def upload_json():
    if request.method == "POST":
        file = request.files.get("json_file")
        if file:
            data = json.load(file)
            for recipe in data:
                db.child("recipes").push(recipe)
        return redirect(url_for("view_recipes"))
    return render_template("upload_json.html")

# ------------------ View Recipes ------------------
@app.route("/recipes")
def view_recipes():
    all_recipes_snapshot = db.child("recipes").get()
    recipes = {}
    categories = set()

    if all_recipes_snapshot.each():
        for snap in all_recipes_snapshot.each():
            rid = snap.key()
            recipe_data = flatten_recipe(snap.val())
            recipe_data.setdefault("ingredients", [])
            recipe_data.setdefault("instructions", "")
            recipe_data.setdefault("category", "Uncategorized")
            recipe_data.setdefault("source", "")
            recipe_data["id"] = rid
            recipes[rid] = recipe_data
            categories.add(recipe_data["category"])

    # Sort recipes by title
    sorted_recipes = dict(sorted(recipes.items(), key=lambda x: x[1]["title"].lower()))
    return render_template("recipes.html", recipes=sorted_recipes, categories=sorted(categories))

# ------------------ View Single Recipe ------------------
@app.route("/view_recipe/<rid>")
def view_recipe(rid):
    snap = db.child("recipes").child(rid).get()
    if not snap.val():
        return "Recipe not found", 404

    recipe = flatten_recipe(snap.val())
    recipe.setdefault("ingredients", [])
    recipe.setdefault("instructions", "")
    recipe.setdefault("category", "Uncategorized")
    recipe.setdefault("source", "")
    recipe["id"] = rid

    return render_template("view_recipe.html", recipe=recipe)

# ------------------ Edit Recipe ------------------
@app.route("/edit_recipe/<rid>", methods=["GET", "POST"])
def edit_recipe(rid):
    snap = db.child("recipes").child(rid).get()
    if not snap.val():
        return "Recipe not found", 404

    recipe = flatten_recipe(snap.val())
    recipe.setdefault("ingredients", [])
    recipe.setdefault("instructions", "")
    recipe.setdefault("category", "Uncategorized")
    recipe.setdefault("source", "")
    recipe["id"] = rid

    if request.method == "POST":
        db.child("recipes").child(rid).update({
            "title": request.form.get("title"),
            "ingredients": [i.strip() for i in request.form.get("ingredients").split(",")],
            "instructions": request.form.get("instructions"),
            "category": request.form.get("category"),
            "source": request.form.get("source")
        })
        return redirect(url_for("view_recipe", rid=rid))

    return render_template("edit_recipe.html", recipe=recipe)

# ------------------ Bulk Export PDF ------------------
@app.route("/bulk_export", methods=["POST"])
def bulk_export():
    selected_ids = request.form.getlist("selected_recipes")
    for rid in selected_ids:
        snap = db.child("recipes").child(rid).get()
        recipe = flatten_recipe(snap.val())
        recipe.setdefault("ingredients", [])
        recipe.setdefault("instructions", "")
        recipe.setdefault("category", "Uncategorized")
        recipe.setdefault("source", "")
        export_recipe_pdf(recipe)
    return "PDFs exported successfully!"

@app.route("/bulk_export_all", methods=["POST"])
def bulk_export_all():
    from reportlab.platypus import KeepTogether, Frame, PageTemplate, BaseDocTemplate, FrameBreak
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    format_type = request.form.get("format", "standard")
    recipes = db.child("recipes").get().val()

    if not recipes:
        flash("No recipes found to export.")
        return redirect(url_for("index"))

    pdf_file = "all_recipes.pdf"
    try:
        pdfmetrics.registerFont(TTFont('Baskerville', 'baskerville.ttf'))
        base_font = 'Baskerville'
    except:
        base_font = 'Times-Roman'  # Fallback if not found

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RecipeTitle", fontName=base_font, fontSize=16, leading=18, alignment=1))
    styles.add(ParagraphStyle(name="RecipeCategory", fontName=base_font, fontSize=10, leading=12, textColor=colors.grey))
    styles.add(ParagraphStyle(name="RecipeText", fontName=base_font, fontSize=10, leading=12))
    styles.add(ParagraphStyle(name="RecipeSubtitle", fontName=base_font, fontSize=12, leading=12))

    if format_type == "standard":
        all_snap = db.child("recipes").get()
        if not all_snap.each():
            return "No recipes to export."

        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet

        pdf_file = "All_Recipes.pdf"
        doc = SimpleDocTemplate(pdf_file, pagesize=letter)
        story = []

        # Loop through all recipes sorted by title
        recipes = []
        for snap in all_snap.each():
            recipe = flatten_recipe(snap.val())
            recipe.setdefault("ingredients", [])
            recipe.setdefault("instructions", "")
            recipe.setdefault("category", "Uncategorized")
            recipe.setdefault("source", "")
            recipes.append(recipe)

        recipes.sort(key=lambda r: r["title"].lower())

        for idx, recipe in enumerate(recipes):
            story.append(Paragraph(f"<b>{recipe['title']}</b>", styles["RecipeTitle"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph(f"<b>Category:</b> {recipe['category']}", styles["RecipeCategory"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph("<b>Ingredients:</b>", styles["RecipeSubtitle"]))
            for ing in recipe["ingredients"]:
                story.append(Paragraph(f"- {ing}", styles["RecipeText"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph("<b>Instructions:</b>", styles["RecipeSubtitle"]))
            story.append(Paragraph(recipe["instructions"], styles["RecipeText"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph(f"<b>Source:</b> {recipe['source']}", styles["RecipeCategory"]))

            if idx != len(recipes) - 1:
                story.append(PageBreak())  # separate recipes

        doc.build(story)
        return send_file(pdf_file, as_attachment=True)


    elif format_type == "cards":
        # Two 5x7" cards per page (top + bottom)
        class TwoPerPageDoc(BaseDocTemplate):
            def __init__(self, filename, **kwargs):
                super().__init__(filename, **kwargs)
                # Each card = 7" wide x 5" tall, centered on letter page (8.5 x 11")
                x_margin = (8.5 * inch - 7 * inch) / 2
                y_top = 11 * inch - 5 * inch - 0.5 * inch
                y_bottom = 0.5 * inch
                card_width = 7 * inch
                card_height = 5 * inch

                self.frames = [
                    Frame(x_margin, y_top, card_width, card_height, id="top"),
                    Frame(x_margin, y_bottom, card_width, card_height, id="bottom")
                ]
                self.addPageTemplates([PageTemplate(id="TwoPerPage", frames=self.frames)])

        doc = TwoPerPageDoc(pdf_file, pagesize=letter)
        story = []

        def build_card(recipe, max_chars=700):
            """
            Build one or more 5x7 cards per recipe with ingredients in two columns.
            Splits instructions automatically if they exceed max_chars.
            Ingredients only appear on the first card.
            Returns a list of Flowables (cards).
            """
            title = recipe.get('title', 'Untitled')
            category = recipe.get('category', 'Uncategorized')
            ingredients_list = recipe.get('ingredients', [])
            instructions = recipe.get('instructions', '').replace("\n", "<br/>")
            source = recipe.get('source', '')

            # Split instructions into manageable chunks
            chunks = [instructions[i:i+max_chars] for i in range(0, len(instructions), max_chars)]
            cards = []

            for i, chunk in enumerate(chunks):
                story = []

                # Title (add continued if not first chunk)
                story.append(Paragraph(title if i == 0 else f"{title} (continued)", styles["RecipeTitle"]))
                story.append(Paragraph(category, styles["RecipeCategory"]))
                story.append(Spacer(1, 6))

                # Only show ingredients on the first card
                if i == 0 and ingredients_list:
                    half = (len(ingredients_list) + 1) // 2
                    col1 = ingredients_list[:half]
                    col2 = ingredients_list[half:]
                    
                    if not col1: col1 = ['']
                    if not col2: col2 = ['']

                    max_rows = max(len(col1), len(col2))
                    col1 += [''] * (max_rows - len(col1))
                    col2 += [''] * (max_rows - len(col2))
                    table_data = [[Paragraph(f"- {c1}", styles["RecipeText"]),
                                Paragraph(f"- {c2}", styles["RecipeText"])] for c1, c2 in zip(col1, col2)]

                    table = Table(table_data, colWidths=[3.0*inch, 3.0*inch])
                    table.setStyle(TableStyle([
                        ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ('LEFTPADDING', (0,0), (-1,-1), 4),
                        ('RIGHTPADDING', (0,0), (-1,-1), 4),
                        ('TOPPADDING', (0,0), (-1,-1), 2),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                    ]))
                    story.append(Paragraph("<b>Ingredients:</b>", styles["RecipeText"]))
                    story.append(table)
                    story.append(Spacer(1, 6))

                # Instructions (always included)
                story.append(Paragraph("<b>Instructions:</b>", styles["RecipeText"]))
                story.append(Paragraph(chunk, styles["RecipeText"]))
                story.append(Spacer(1, 6))

                # Source only on last chunk
                if i == len(chunks) - 1 and source:
                    story.append(Paragraph(f"<i>Source:</i> {source}", styles["RecipeCategory"]))

                cards.append(KeepTogether(story))

            return cards


        recipes_list = list(recipes.values())
        recipes_list.sort(key=lambda r: r.get("title", "").lower())

        for recipe in recipes_list:
            for card in build_card(recipe):
                story.append(card)
                story.append(FrameBreak())



        doc.build(story)
        return send_file(pdf_file, as_attachment=True)

@app.route("/bulk_export_selected", methods=["POST"])
def bulk_export_selected():
    selected_ids = request.form.getlist("selected_recipes")
    if not selected_ids:
        return "No recipes selected."

    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet

    pdf_file = "Selected_Recipes.pdf"
    doc = SimpleDocTemplate(pdf_file, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    for idx, rid in enumerate(selected_ids):
        snap = db.child("recipes").child(rid).get()
        recipe = flatten_recipe(snap.val())
        recipe.setdefault("ingredients", [])
        recipe.setdefault("instructions", "")
        recipe.setdefault("category", "Uncategorized")
        recipe.setdefault("source", "")

        story.append(Paragraph(f"<b>{recipe['title']}</b>", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"<b>Category:</b> {recipe['category']}", styles["Normal"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph("<b>Ingredients:</b>", styles["Heading3"]))
        for ing in recipe["ingredients"]:
            story.append(Paragraph(f"- {ing}", styles["Normal"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph("<b>Instructions:</b>", styles["Heading3"]))
        story.append(Paragraph(recipe["instructions"], styles["Normal"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"<b>Source:</b> {recipe['source']}", styles["Italic"]))

        if idx != len(selected_ids) - 1:
            story.append(PageBreak())

    doc.build(story)
    return send_file(pdf_file, as_attachment=True)


@app.route("/download_template")
def download_template():
    """
    Generates a PDF with two blank 5x7 rectangles per page for recipe cards.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Card size: 7" wide x 5" tall
    card_width = 7 * inch
    card_height = 5 * inch

    # Margins for centering cards
    x_margin = (width - card_width) / 2
    top_y = height - card_height - 0.5*inch
    bottom_y = 0.5*inch

    # Draw top card rectangle
    c.rect(x_margin, top_y, card_width, card_height)
    
    # Draw bottom card rectangle
    c.rect(x_margin, bottom_y, card_width, card_height)

    c.showPage()
    c.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="recipe_card_template.pdf", mimetype="application/pdf")

# ------------------ Run App ------------------
#if __name__ == "__main__":
#    app.run(debug=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Render expects port 10000 by default
    app.run(host="0.0.0.0", port=port, debug=False)
