import argparse
import sys
import json
import traceback
import os

# Hack around absolute paths
current_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = os.path.abspath(current_dir + "/../")

sys.path.insert(0, parent_dir)


from bottle import Bottle, run, template, get, post, request, static_file, url, debug
import sqlite3





app = Bottle()
# conn to db
conn=sqlite3.connect('../blockversion.db')
print "Database connected and opened" + repr('../blockversion.db')
cur = conn.cursor()

# Static Routes

@app.get('/<filename:re:.*\.js>')
def javascripts(filename):
    return static_file(filename, root='static/js')

@app.get('/<filename:re:.*\.(css|map)>')
def stylesheets(filename):
    return static_file(filename, root='static/css')

@app.get('/<filename:re:.*\.(jpg|png|gif|ico)>')
def images(filename):
    return static_file(filename, root='static/images')

@app.get('/<filename:re:.*\.(ttf|woff|woff2|svg|eot)>')
def fonts(filename):
    return static_file(filename, root='static/fonts')

#BASE
@app.route('/')
def home():
    my_dict = {}

    #return template("index.html", **my_dict)
    return template("index.html")
    #return "<p>Welcome to ReddID, Please see ___ for details</p>"

@app.route('/api/blockversion_test')
def version():
    resp = {}

    # get last record
    cur.execute ("SELECT * FROM blocks WHERE ID = (SELECT MAX(ID) FROM blocks)")
    data = cur.fetchone()
    lastblock = data[1]
    firstblock = data[1] - 7200
    # get count of 
    query = "SELECT count(*) FROM blocks WHERE VERSION = 4 AND BLOCK > " + repr(lastblock - 7200) + " AND BLOCK <= " + repr(lastblock)
    cur.execute (query)
    data = cur.fetchone()
    v4_blocks =data[0]
    percent = float(v4_blocks) / 7200
    query = "SELECT * FROM blocks LEFT OUTER JOIN blockversion ON blocks.BLOCK = blockversion.HEIGHT WHERE BLOCK > " + repr(lastblock - 14400) + " AND BLOCK <= " + repr(lastblock)
    cur.execute (query)
    data = cur.fetchall()
    v3begin = data[7199][9] - data[0][9]
    v4begin = data[7199][10] - data[0][10]

    newdata = ()
    for i in range (7200,14400):
        v3begin = (data[i][9] - data[i-7200][9])
        v4begin = (data[i][10] - data[i-7200][10])
        newdata = newdata + (data[i] + (v3begin, ) + (v4begin,),)

    #print data[0]
    resp['firstblock'] = firstblock
    resp['lastblock'] = lastblock
    resp['range'] = lastblock - firstblock
    resp['percent'] = newdata[7200-1][12] / 7200.0
    resp['blocks'] = newdata[7200-1]



    #return template('<p>System Version: {{version}}.</p>', version=data[1])
    return json.dumps(resp)
@app.route('/api/blockversion', method='GET')
def version():
    resp = {}


    # get last record
    cur.execute ("SELECT * FROM blocks WHERE ID = (SELECT MAX(ID) FROM blocks)")
    data = cur.fetchone()
    lastblock = data[1]
    firstblock = data[1] - 7200
    # get count of 
    query = "SELECT count(*) FROM blocks WHERE VERSION = 4 AND BLOCK > " + repr(lastblock - 7200) + " AND BLOCK <= " + repr(lastblock)
    cur.execute (query)
    data = cur.fetchone()
    v4_blocks =data[0]
    percent = float(v4_blocks) / 7200
    query = "SELECT * FROM blocks LEFT OUTER JOIN blockversion ON blocks.BLOCK = blockversion.HEIGHT WHERE BLOCK > " + repr(lastblock - 14400) + " AND BLOCK <= " + repr(lastblock)
    cur.execute (query)
    data = cur.fetchall()
    v3begin = data[7199][9] - data[0][9]
    v4begin = data[7199][10] - data[0][10]

    newdata = ()
    for i in range (7200,14400):
        v3begin = (data[i][9] - data[i-7200][9])/7200.0
        v4begin = (data[i][10] - data[i-7200][10])/7200.0
        newdata = newdata + ((data[i][1],) + (v4begin,),)
    """
    #print data[0]
    resp['firstblock'] = firstblock
    resp['lastblock'] = lastblock
    resp['range'] = lastblock - firstblock
    resp['percent'] = newdata[7200-1][12] / 7200.0
    resp['blocks'] = newdata[7200-1]

    """
    return json.dumps(newdata)
@app.route('/api/difficulty', method='GET')
def version():
    resp = {}


    # get last record
    cur.execute ("SELECT * FROM blocks WHERE ID = (SELECT MAX(ID) FROM blocks)")
    data = cur.fetchone()
    lastblock = data[1]
    firstblock = data[1] - 7200
    # get count of 
    query = "SELECT block, difficulty FROM blocks WHERE BLOCK > " + repr(lastblock - 7200) + " AND BLOCK <= " + repr(lastblock)
    cur.execute (query)
    data = cur.fetchall()

    return json.dumps(data)

@app.route('/api/v4_bip66')
def version():
    resp = {}

    cur.execute ("SELECT * FROM blocks WHERE ID = (SELECT MAX(ID) FROM blocks)")
    data = cur.fetchone()
    lastblock = data[1]
    firstblock = data[1] - 7200
    query = "SELECT count(*) FROM blocks WHERE VERSION = 4 AND BLOCK > " + repr(firstblock) + " AND BLOCK <= " + repr(lastblock)
    cur.execute (query)
    data = cur.fetchone()
    v4_blocks =data[0]
    percent = float(v4_blocks) / 7200
    resp['firstblock'] = firstblock
    resp['lastblock'] = lastblock
    resp['percent'] = percent * 100


    #return template('<p>System Version: {{version}}.</p>', version=data[1])
    return json.dumps(resp)
@app.route('/status')
def status():
    #return template('<p>System Status: {{status}}.</p>', status=json.dumps(client.getinfo(), sort_keys=True, indent=4, separators=(',',': ')))
    status = client.getinfo()
    return template('status.html', **status)
    #return template('status.html', status=json.dumps(client.getinfo(), sort_keys=True, indent=4, separators=(',',': ')))

@app.route('/api/status')
def status():
    status = client.getinfo()
    return status

##WEBSITE
@app.route('/what_is_reddid')
def status():
    return template('what_is_reddid')


#NAME
@app.get('/name/details')
def name_cost():
    return template('name_details')


#NAME Lookup
@app.route('/name/lookup', method='GET')
def name_lookup():
    resp = {}
    resp['name'] = ''
    return template('name_lookup', **resp)

@app.route('/name/lookup', method='POST')
def name_lookup():
    resp = {}
    username = request.forms.get('username')
    resp['name'] = username
    resp['status'] = client.get_name_blockchain_record(str(username + '.test'))
    return template('name_lookup', **resp)

@app.route('/api/name/lookup/<name>')
def name_lookup(name):
    return template('<p>Lookup of {{name}} is {{status}}</p>', name=name, status=client.get_name_blockchain_record(str(name + '.test')))

#NAME Price
@app.route('/name/price', method='GET')
def name_price():
    resp = {}
    resp['price']=0
    return template('name_price', **resp)

@app.route('/name/price', method='POST')
def name_price():
    resp = {}
    username = request.forms.get('username')
    resp['name'] = username
    resp['price'] = client.get_name_cost(str(username + '.test'))
    return template('name_price', **resp)

@app.route('/api/name/price/<name>')
def name_price(name):
    return template('<p>Price of {{name}} is {{price}}</p>', name=name, price=client.get_name_cost(str(name + '.test')))

#NAME
@app.get('/name/register')
def name_register():
    return template('name_register')

#NAME order
@app.route('/v1/name/preorder/<name>/<privaddress>/<address>')
def name_preorder(name, privaddress, address):
    return template('<p>Preorder of {{name}} is {{status}}</p>', name=name, status=client.preorder(str(name + '.test'), str(privaddress), str('tx_only=True')))

#NAMESPACE Price
@app.route('/namespace/price', method='GET')
def namespace_price():
    resp = {}
    resp['price']=0
    return template('namespace_price', **resp)

@app.route('/namespace/price', method='POST')
def namespace_price():
    resp = {}
    namespace = request.forms.get('namespace')
    resp['name'] = namespace
    resp['price'] = client.get_namespace_cost(str(namespace),proxy)
    return template('namespace_price', **resp)

@app.route('/api/namespace/price/<namespace>')
def namespace_price(namespace):
    return template('<p>Price of {{name}} is {{price}}</p>', name=namespace, price=client.get_namespace_cost(str(namespace),proxy))

#NAMESPACE Lookup
@app.route('/namespace/lookup', method='GET')
def namespace_lookup():
    resp = {}
    resp['name'] = ''
    return template('namespace_lookup', **resp)

@app.route('/namespace/lookup', method='POST')
def namespace_lookup():
    resp = {}
    namespace = request.forms.get('namespace')
    resp['name'] = namespace
    resp['status'] = client.get_namespace_blockchain_record(str(namespace))
    return template('namespace_lookup', **resp)

@app.route('/api/namespace/lookup/<name>')
def name_lookup(namespace):
    return template('<p>Lookup of {{name}} is {{status}}</p>', name=namespace, status=client.get_namespace_blockchain_record(str(namespace)))

@app.route('/login') # or @route('/login')
def login():
    return '''
        <form action="/login" method="post">
            Username: <input name="username" type="text" />
            Password: <input name="password" type="password" />
            <input value="Login" type="submit" />
        </form>
    '''
@app.route('/login', method="POST") # or @route('/login', method='POST')
def do_login():
    username = request.forms.get('username')
    password = request.forms.get('password')
    if check_login(username, password):
        return "<p>Your login information was correct.</p>"
    else:
        return "<p>Login failed.</p>"

debug(True)
run(app, host='0.0.0.0', port=8085, debug=False, reloader=True)
