from flask import Flask, render_template, request, jsonify
import pickle
import numpy as np
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
from bs4 import BeautifulSoup
import time

# Load preprocessed data
popular_df = pickle.load(open("popular.pkl", 'rb'))
pt = pickle.load(open("pk.pkl", 'rb'))
books = pickle.load(open("books.pkl", 'rb'))
similarity_scores = pickle.load(open("similarity_scores.pkl", 'rb'))

API_KEY = "AIzaSyAMzPWFgg32yLLQAlih9GBuzneh7je951I"

app = Flask(__name__)

def get_goodreads_id(book_title):
    """Fetch book ID from Goodreads"""
    search_url = f"https://www.goodreads.com/search?q={book_title.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0"}  # Avoid bot detection

    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Request error: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    book_link = soup.select_one(".bookTitle")

    if book_link:
        book_url = "https://www.goodreads.com" + book_link["href"]
        try:
            book_id = book_url.split("/book/show/")[1].split("-")[0]  # Extract numeric ID
            return book_id
        except IndexError:
            return None
    return None

def get_goodreads_reviews(book_id, num_reviews=5):
    """Scrape user reviews from Goodreads"""
    if not book_id:
        return []

    review_url = f"https://www.goodreads.com/book/show/{book_id}"

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    driver.get(review_url)
    time.sleep(3)  # Allow JavaScript to load

    reviews = []

    try:
        review_divs = driver.find_elements(By.CLASS_NAME, "ReviewText")[:num_reviews]  # Update this if class changes
        for review_div in review_divs:
            reviews.append(review_div.text.strip())
    except Exception as e:
        print(f"⚠️ Error fetching reviews: {e}")

    driver.quit()
    
    return reviews

@app.route('/')
def index():
    return render_template("index.html",
                           book_name=list(popular_df['Book-Title'].values),
                           author=list(popular_df['Book-Author'].values),
                           image=list(popular_df['Image-URL-M'].values),
                           votes=list(popular_df['num_Ratings'].values),
                           ratings=list(popular_df['avg_rating'].values),
                           )

@app.route("/recommend")
def recommend_ui():
    return render_template("recommend.html")

@app.route("/recommend_books", methods=['POST'])
def recommend():
    user_input = request.form.get("user_input", "").strip()

    # Check if input book exists in the dataset
    if not user_input or user_input not in pt.index:
        return jsonify([])  # Return empty list if book not found

    try:
        index = np.where(pt.index == user_input)[0][0]
        similar_items = sorted(
            list(enumerate(similarity_scores[index])),
            key=lambda x: x[1],
            reverse=True
        )[1:6]  # Get top 5 recommendations

        recommendations = []
        for i in similar_items:
            temp_df = books[books["Book-Title"] == pt.index[i[0]]].drop_duplicates("Book-Title")
            if not temp_df.empty:
                book_data = {
                    "title": temp_df["Book-Title"].values[0],
                    "author": temp_df["Book-Author"].values[0],
                    "image_url": temp_df["Image-URL-M"].values[0]
                }
                recommendations.append(book_data)

        return jsonify(recommendations)  # Return JSON response

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"})
    
@app.route("/get_reviews", methods=["POST"])
def get_reviews():
    """Handles AJAX request from frontend"""
    data = request.json
    book_title = data.get("book_title")

    if not book_title:
        return jsonify({"error": "No book title provided"}), 400

    book_id = get_goodreads_id(book_title)

    if not book_id:
        return jsonify({"error": "Book not found"}), 404

    reviews = get_goodreads_reviews(book_id)

    return jsonify({"reviews": reviews})

@app.route("/book_details/<book_name>")
def book_details(book_name):
    try:
        # Fetch book details from Google Books API
        google_books_url = f"https://www.googleapis.com/books/v1/volumes?q={book_name}&key={API_KEY}"
        response = requests.get(google_books_url).json()

        if "items" in response and len(response["items"]) > 0:
            book_info = response["items"][0]["volumeInfo"]
            details = {
                "title": book_info.get("title", "Unknown Title"),
                "authors": book_info.get("authors", ["Unknown Author"]),
                "publisher": book_info.get("publisher", "Unknown Publisher"),
                "publishedDate": book_info.get("publishedDate", "Unknown Date"),
                "description": book_info.get("description", "No description available."),
                "image": book_info.get("imageLinks", {}).get("thumbnail", "https://via.placeholder.com/150"),
            }
        else:
            details = {"title": book_name, "error": "Book details not found"}

        # Fetch book recommendations
        recommendations_response = requests.post("http://127.0.0.1:5000/recommend_books", json={"book_title": book_name})
        recommendations = recommendations_response.json() if recommendations_response.status_code == 200 else []

        # Fetch reviews
        reviews_response = requests.post("http://127.0.0.1:5000/get_reviews", json={"book_title": book_name})
        reviews = reviews_response.json().get("reviews", []) if reviews_response.status_code == 200 else []

        return render_template("book_details.html", details=details, recommendations=recommendations, reviews=reviews)

    except Exception as e:
        return f"Error: {str(e)}", 500  # Return a proper error message


if __name__ == "__main__":
    app.run(debug=True)