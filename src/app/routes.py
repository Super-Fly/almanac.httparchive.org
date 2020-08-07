from .helpers import render_template, render_error_template, convert_old_image_path
from .validate import validate
from flask import abort, redirect, url_for, request, send_from_directory
from config import get_config, DEFAULT_YEAR
import random
import logging


def configure(app, talisman):
    @app.after_request
    def add_header(response):
        # Make sure bad responses are not cached
        #
        # Cache good responses for 3 hours if no other Cache-Control header set
        # This is used for the dynamically generated files (e.g. the HTML)
        # (currently don't use unique filenames so cannot use long caches and
        # some say they are overrated anyway as caches smaller than we think).
        # Note this IS used by Google App Engine as dynamic content.
        if 'Cache-Control' not in response.headers:
            if response.status_code != 200 and response.status_code != 304:
                response.cache_control.no_store = True
                response.cache_control.no_cache = True
                response.cache_control.max_age = 0
            if response.status_code == 200 or response.status_code == 304:
                response.cache_control.public = True
                response.cache_control.max_age = 10800
        return response

    @app.route('/<lang>/<year>/')
    @validate
    def home(lang, year):
        config = get_config(year)
        return render_template('%s/%s/index.html' % (lang, year), config=config)

    @app.route('/<lang>/')
    @validate
    def lang_only(lang):
        return redirect(url_for('home', lang=lang, year=DEFAULT_YEAR))

    @app.route('/')
    @validate
    def root(lang):
        response = redirect(url_for('home', lang=lang, year=DEFAULT_YEAR))
        response.vary = 'Accept-Language'
        return response

    @app.route('/<lang>/<year>/table-of-contents')
    @validate
    def table_of_contents(lang, year):
        config = get_config(year)
        return render_template('%s/%s/table_of_contents.html' % (lang, year), config=config)

    @app.route('/<lang>/<year>/contributors')
    @validate
    def contributors(lang, year):
        config = get_config(year)
        contributors_list = list(config["contributors"].items())
        random.shuffle(contributors_list)
        config["contributors"] = dict(contributors_list)
        return render_template('%s/%s/contributors.html' % (lang, year), config=config)

    @app.route('/<lang>/<year>/methodology')
    @validate
    def methodology(lang, year):
        return render_template('%s/%s/methodology.html' % (lang, year))

    # Accessibility Statement needs special case handling for trailing slashes
    # as, unlike Flask, we generally prefer no trailing slashes
    # For chapters we handle this in the validate function
    @app.route('/<lang>/accessibility-statement', strict_slashes=False)
    @validate
    def accessibility_statement(lang):
        if request.base_url[-1] == "/":
            return redirect("/%s/accessibility-statement" % (lang)), 301
        else:
            return render_template('%s/2019/accessibility_statement.html' % (lang))

    @app.route('/sitemap.xml')
    # Chrome and Safari use inline styles to display XMLs files.
    # https://bugs.chromium.org/p/chromium/issues/detail?id=924962
    # Override default CSP (including turning off nonce) to allow sitemap to display
    @talisman(
        content_security_policy={'default-src': ['\'self\''], 'script-src': ['\'self\''],
                                 'style-src': ['\'unsafe-inline\''], 'img-src': ['\'self\'', 'data:']},
        content_security_policy_nonce_in=['script-src']
    )
    def sitemap():
        # Flask-Talisman doesn't allow override of content_security_policy_nonce_in
        # per route yet
        # https://github.com/GoogleCloudPlatform/flask-talisman/issues/62
        # So remove Nonce value from request object for now which has same effect
        delattr(request, 'csp_nonce')
        xml = render_template('sitemap.xml')
        resp = app.make_response(xml)
        resp.mimetype = "text/xml"
        return resp

    # Assume anything else with at least 3 directories is a chapter
    # so we can give lany and year specific error messages
    @app.route('/<lang>/<year>/<path:chapter>')
    @validate
    def chapter(lang, year, chapter):
        config = get_config(year)
        (prev_chapter, next_chapter) = get_chapter_nextprev(config, chapter)
        return render_template('%s/%s/chapters/%s.html' % (lang, year, chapter), config=config,
                               prev_chapter=prev_chapter, next_chapter=next_chapter)

    def get_chapter_nextprev(config, chapter_slug):
        prev_chapter = None
        next_chapter = None
        found = False

        for part in config['outline']:
            for chapter in part['chapters']:
                if found and 'todo' not in chapter:
                    next_chapter = chapter
                    break
                elif chapter.get('slug') == chapter_slug and 'todo' not in chapter:
                    found = True
                elif 'todo' not in chapter:
                    prev_chapter = chapter
            if found and next_chapter:
                break

        return prev_chapter, next_chapter

    @app.route('/robots.txt')
    def static_from_root():
        return send_from_directory(app.static_folder, request.path[1:])

    @app.route('/favicon.ico')
    def default_favicon():
        return send_from_directory(app.static_folder, 'images/favicon.ico')

    @app.route('/<lang>/<year>/ebook')
    @validate
    def ebook(lang, year):
        config = get_config(year)
        sorted_contributors = sorted(config["contributors"].items(), key=lambda items: items[1]['name'])
        config["contributors"] = dict(sorted_contributors)
        return render_template('%s/%s/ebook.html' % (lang, year), config=config)

    # Redirect requests for the older image URLs to new URLs
    @app.route('/static/images/2019/<regex("[0-2][0-9]_.*"):folder>/<image>')
    def redirect_old_images(folder, image):
        return redirect("/static/images/2019/%s/%s" % (convert_old_image_path(folder), image)), 301

    # Catch all route for everything not matched elsewhere
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all(path):
        abort(404, "Not Found")

    @app.errorhandler(400)
    def bad_request(e):
        logging.exception('An error occurred during a request due to bad request error: %s', request.path)
        return render_error_template(error=e, status_code=400)

    @app.errorhandler(404)
    def page_not_found(e):
        return render_error_template(error=e, status_code=404)

    @app.errorhandler(500)
    def handle_internal_server_error(e):
        logging.exception('An error occurred during a request due to internal server error: %s', request.path)
        return render_error_template(error=e, status_code=500)

    @app.errorhandler(502)
    def handle_bad_gateway(e):
        logging.exception('An error occurred during a request due to bad gateway: %s', request.path)
        return render_error_template(error=e, status_code=502)
