import os
import pickle
import json
import operator
import datetime
import jwt
try:
    import configparser
except ImportError:
    import ConfigParser as configparser

from flask import Flask, request, Response, url_for, make_response

#import rdflib
import numpy as np
import scipy.spatial
import scipy.linalg

import pressagio.callback
import pressagio

import sqlite3

# Import Flask app
from main import app
#from main import dbconnections

class DemoCallback(pressagio.callback.Callback):
    def __init__(self, buffer):
        pressagio.callback.Callback.__init__(self)
        self.buffer = buffer

    def past_stream(self):
        return self.buffer
    
    def future_stream(self):
        return ''


con = sqlite3.connect(os.path.abspath(os.path.join(app.static_folder, "limits.sqlite")), check_same_thread=False)
cur = con.cursor()

################################################### API routes

@app.route("/api/semantics")
def api_semantics():
    if check_request("semantics"):
        return Response(json.dumps(get_semantic_map()), mimetype='application/json')
    else:
        return Response("Sorry, you have reached the number of allowed requests for today.")

@app.route("/api/prediction")
def api_prediction():
    if check_request("prediction"):
        return Response(json.dumps(get_prediction()), mimetype='application/json')
    else:
        return Response("Sorry, you have reached the number of allowed requests for today.")

@app.route("/api/languages")
def api_languages():
    if check_request("languages"):
        return Response(json.dumps(get_supported_languages()), mimetype='application/json')
    else:
        return Response("Sorry, you have reached the number of allowed requests for today.")

@app.route("/api/corpus")
def api_corpus():
    if check_request("corpus"):
        return Response(json.dumps(get_corpus_files()), mimetype='application/json')
    else:
        return Response("Sorry, you have reached the number of allowed requests for today.")


################################################### Helpers

def check_request(table):
    token = request.args.get('token', '', type=str)
    if token == '':
        if limit_reached(table):
            return False
    else:
        try:
            jwt.decode(token, "supersecret")
        except:
            return False
    return True


def get_prediction():
    iso = request.args.get('iso', '', type=str)
    predictions = []
    if iso != 'none':
        string_buffer = request.args.get('text', '')

        db_file = os.path.abspath(os.path.join(app.static_folder, 'prediction', "{0}.sqlite".format(iso)))
        config_file = os.path.join(app.static_folder, 'prediction', "{0}.ini".format(iso))
        config = configparser.ConfigParser()
        config.read(config_file)
        dbconnection = None
        if config.get("Database", "class") == 'PostgresDatabaseConnector':
            config.set("Database", "database", iso)
#            if iso in dbconnections:
#                dbconnection = dbconnections[iso]
        else:
            config.set("Database", "database", db_file)

        callback = DemoCallback(string_buffer)
        prsgio = pressagio.Pressagio(callback, config, dbconnection)
        predictions = prsgio.predict()
        prsgio.close_database()

    return predictions


def get_semantic_map(iso = None, term = None):
    if not iso:
        iso = request.args.get('iso', '', type=str)
    if not term:
        term = request.args.get('term', '')

    plot_dir = os.path.join(app.static_folder, 'plots')
    plot_filename = u"{0}-{1}.pickle".format(iso, term)
    plot_filepath = os.path.join(plot_dir, plot_filename)

    if os.path.exists(plot_filepath):
        inputfile = open(plot_filepath, 'rb')
        graphdata = pickle.load(inputfile)
        inputfile.close()
        return graphdata

    sem_dir = os.path.join(app.static_folder, 'semantics')

    indices_file = os.path.join(sem_dir, "{0}-indices.pickle".format(iso))
    with open(indices_file, "rb") as f:
        indices = pickle.load(f)
        keys = [k 
            for k, _ in sorted(indices.items(), key=operator.itemgetter(1))]
    if not term in indices:
        return None


    ut_file = os.path.join(sem_dir, "{0}-ut.bin".format(iso))
    with open(ut_file, "rb") as f:
        ut = np.load(f)
    s_file = os.path.join(sem_dir, "{0}-s.bin".format(iso))
    with open(s_file, "rb") as f:
        s = np.load(f)
    vt_file = os.path.join(sem_dir, "{0}-vt.bin".format(iso))
    with open(vt_file, "rb") as f:
        vt = np.load(f)

    reconstructed_matrix = np.dot(ut.T, np.dot(np.diag(s), vt))
    tree = scipy.spatial.cKDTree(reconstructed_matrix)
    neighbours = tree.query(reconstructed_matrix[indices[term]], k=50)

    subset = reconstructed_matrix[neighbours[1]]
    words = [keys[i] for i in neighbours[1]]
    tempU, tempS, tempVt = scipy.linalg.svd(subset)

    graphdata = []
    count = 0
    for element in tempU[:,1]:
        graphdata.append([words[count], element, tempU[:,2][count]])
        count += 1

    outputfile = open(plot_filepath, 'wb')
    pickle.dump(graphdata, outputfile)
    outputfile.close()

    return graphdata


def get_supported_languages():
    languages_list = []
    for element in languages_data():
        languages_list.append(element)

    return sorted(languages_list)


def get_corpus_files():
    iso = request.args.get('iso', '', type=str)
    
    if iso in get_supported_languages():
        files = []
        for filename in languages_data()[iso]["files"]:
            files.append(url_for('static', filename="corpus/" + filename, _external=True ))

        return files


def languages_data():
    languages_data = dict()
    languages_data_file = os.path.join(app.static_folder, 'langinfo', 'languages_data.pickle')
    with open(languages_data_file, "rb") as f:
        languages_data = pickle.load(f)
    return languages_data


def limit_reached(table):
    if table == "languages":
        requestsLimit = 1000
    if table == "corpus":
        requestsLimit = 1000
    if table == "prediction":
        requestsLimit = 10000
    if table == "semantics":
        requestsLimit = 100

    ip = str(request.remote_addr)
    date = datetime.date.today()

    cur.execute("select * from {0} where ip == '{1}'".format(table, ip))
    if len(cur.fetchall()) == 0:
        cur.execute("INSERT INTO {0} VALUES ('{1}', '{2}', 1)".format(table, ip, date))

    cur.execute("SELECT count FROM {0} WHERE ip='{1}'".format(table, ip))
    count = int(cur.fetchall()[0][0])
    print count

    if count > requestsLimit:
        return True

    cur.execute("UPDATE {0} SET count={1} WHERE ip='{2}'".format(table, str(count + 1), ip))
    con.commit()    
    return False
