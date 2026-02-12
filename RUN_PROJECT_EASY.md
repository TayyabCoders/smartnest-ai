# Step-by-Step Guide: How to Run This Project

Follow these exact steps to get your project up and running. I have made this as simple as possible.

---

### **Step 1: Check if you have Python**
Open your terminal (Command Prompt or PowerShell) and type:
```bash
python --version
```
*   **Success:** You should see `Python 3.11` or higher.
*   **If not:** Download it from [python.org](https://www.python.org/).

---

### **Step 2: Check for `uv` (The Package Manager)**
Type:
```bash
uv --version
```
*   **If you see a version number:** Great! Skip to Step 3.
*   **If you get an error ("uv is not recognized"):** Install it by typing:
    ```bash
    pip install uv
    ```

---

### **Step 3: Check for Docker (For the Database)**
Type:
```bash
docker --version
```
*   **Success:** You should see a version number. Make sure the **Docker Desktop** app is actually running on your computer.
*   **If not:** You need to install [Docker Desktop](https://www.docker.com/products/docker-desktop/) to run the database.

---

### **Step 4: Prepare the Project**
Navigate to your project folder in the terminal:
```bash
cd "d:\360ExpertsTrainee\Project\parking_system"
```

Now, install all the "brains" and libraries the project needs:
```bash
uv sync
```
*(This might take a few minutes as it downloads AI models like PaddleOCR).*

---

### **Step 5: Start the Database**
Turn on the database so the project has a place to save data:
```bash
docker compose up -d db
```

---

### **Step 6: Create your Admin User**
You need an account to log in. Run this command to create one:
```bash
uv run python scripts/create_user.py --email admin@example.com --password "admin123" --full-name "Project Admin"
```
*Save those login details:*
*   **Email:** `admin@example.com`
*   **Password:** `admin123`

---

### **Step 7: Run the Project!**
Finally, start the server:
```bash
uv run uvicorn app.services.main:app --host 0.0.0.0 --port 8000 --reload
```

---

### **Step 8: How to verify it's working**
1.  Open your browser and go to: **[http://localhost:8000/docs](http://localhost:8000/docs)**
2.  If you see a page with "FastAPI" and a list of links (Auth, Parking), **CONGRATULATIONS!** Your project is working perfectly.

---

### **Next Steps?**
Now that it's running, follow the **[API_TESTING_GUIDE.md](file:///d:/360ExpertsTrainee/Project/parking_system/API_TESTING_GUIDE.md)** to test the vehicle detection features.
