import os
import json
import logging
from sqlalchemy import Column, String, Integer, text
from flask_sqlalchemy import SQLAlchemy
from flask import Flask, render_template, request, jsonify
from sqlalchemy.exc import OperationalError

# Set up logging
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
application = app
app.logger.setLevel(logging.DEBUG)

# Configure database
db_path = os.path.abspath('volusia_inmates.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True

db = SQLAlchemy()
db.init_app(app)

# Test database connection
try:
    with app.app_context():
        db.session.execute(text("SELECT 1")).scalar()
        app.logger.info("Database connection successful")
except Exception as e:
    app.logger.error(f"Failed to connect to database: {e}")

class Inmate(db.Model):
    __tablename__ = 'inmates'
    id = Column(Integer, primary_key=True)
    booking_num = Column(String, unique=True)
    inmate_id = Column(String)
    last_name = Column(String)
    first_name = Column(String)
    middle_name = Column(String)
    suffix = Column(String)
    sex = Column(String)
    race = Column(String)
    booking_date = Column(String)
    release_date = Column(String)
    in_custody = Column(String)
    photo_link = Column(String)
    charges = Column(String)

@app.route('/')
def index():
    try:
        # Verify database file exists
        if not os.path.exists('volusia_inmates.db'):
            app.logger.error("Database file volusia_inmates.db not found")
            return render_template('error.html',
                                  heading='Database Not Found',
                                  error_message='The database file is missing. Please run the scraper first.')

        # Get search parameters
        search_name = request.args.get('search_name', '').strip()
        search_race = request.args.get('search_race', '').strip()
        search_gender = request.args.get('search_gender', '').strip()
        page = int(request.args.get('page', 1))
        per_page = 50

        # Build query
        query = "SELECT * FROM inmates WHERE 1=1"
        params = []

        if search_name:
            query += " AND (last_name LIKE ? OR first_name LIKE ?)"
            params.extend([f'%{search_name}%', f'%{search_name}%'])

        if search_race:
            query += " AND race LIKE ?"
            params.append(f'%{search_race}%')

        if search_gender:
            query += " AND sex LIKE ?"
            params.append(f'%{search_gender}%')

        query += " ORDER BY booking_date DESC"

        # Get total count for pagination
        count_query = query.replace("SELECT * FROM inmates", "SELECT COUNT(*) FROM inmates")
        total_inmates = db.session.execute(text(count_query), params).scalar()

        # Add pagination
        offset = (page - 1) * per_page
        query += f" LIMIT {per_page} OFFSET {offset}"

        inmates = db.session.execute(text(query), params).all()
        inmate_data = []

        for row in inmates:
            try:
                charges = json.loads(row.charges) if row.charges else []
            except json.JSONDecodeError as e:
                app.logger.error(f"Invalid JSON in charges for booking_num {row.booking_num}: {e}")
                charges = []

            inmate = {
                'id': row.id,
                'booking_num': row.booking_num,
                'inmate_id': row.inmate_id,
                'last_name': row.last_name,
                'first_name': row.first_name,
                'middle_name': row.middle_name,
                'suffix': row.suffix,
                'sex': row.sex,
                'race': row.race,
                'booking_date': row.booking_date,
                'release_date': row.release_date,
                'in_custody': row.in_custody,
                'photo_link': row.photo_link,
                'charges': charges,
                'charge_count': len(charges)
            }
            inmate_data.append(inmate)

        if not inmate_data and not any([search_name, search_race, search_gender]):
            app.logger.warning("No inmates found in database")
            return render_template('error.html',
                                  heading='No Inmate Data',
                                  error_message='The database is empty. Please run the scraper to populate it.')

        # Pagination info
        total_pages = (total_inmates + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages

        return render_template('index.html', 
                             inmates=inmate_data,
                             search_name=search_name,
                             search_race=search_race,
                             search_gender=search_gender,
                             page=page,
                             total_pages=total_pages,
                             has_prev=has_prev,
                             has_next=has_next,
                             total_inmates=total_inmates)

    except OperationalError as e:
        app.logger.error(f"Database error: {e}")
        return render_template('error.html',
                              heading='Database Connection Failed',
                              error_message='Unable to access inmate data. Please ensure the database is populated.')
    except Exception as e:
        app.logger.error(f"Unexpected error: {e}")
        return render_template('error.html',
                              heading='Internal Server Error',
                              error_message='An unexpected error occurred. Please try again later.')

@app.route('/inmate/<int:inmate_id>')
def inmate_detail(inmate_id):
    try:
        inmate = db.session.execute(text("SELECT * FROM inmates WHERE id = ?"), [inmate_id]).first()
        
        if not inmate:
            return render_template('error.html',
                                  heading='Inmate Not Found',
                                  error_message='The requested inmate could not be found.')

        try:
            charges = json.loads(inmate.charges) if inmate.charges else []
        except json.JSONDecodeError:
            charges = []

        inmate_data = {
            'id': inmate.id,
            'booking_num': inmate.booking_num,
            'inmate_id': inmate.inmate_id,
            'last_name': inmate.last_name,
            'first_name': inmate.first_name,
            'middle_name': inmate.middle_name,
            'suffix': inmate.suffix,
            'sex': inmate.sex,
            'race': inmate.race,
            'booking_date': inmate.booking_date,
            'release_date': inmate.release_date,
            'in_custody': inmate.in_custody,
            'photo_link': inmate.photo_link,
            'charges': charges
        }

        return render_template('inmate_detail.html', inmate=inmate_data)

    except Exception as e:
        app.logger.error(f"Error fetching inmate details: {e}")
        return render_template('error.html',
                              heading='Error',
                              error_message='An error occurred while fetching inmate details.')

if __name__ == '__main__':
    app.run(debug=True)