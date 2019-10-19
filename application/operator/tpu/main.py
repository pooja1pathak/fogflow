from flask import Flask, jsonify, abort, request, make_response
import requests 
import json
import time
import datetime
import threading
import os
from PIL import Image
from io import BytesIO
from threading import Lock, Thread

lock = Lock()

# edge-tpu
from embedding import kNNEmbeddingEngine

## parameter configuration
model_path = "test_data/mobilenet_v2_1.0_224_quant_edgetpu.tflite"
width = 224
height = 224

kNN = 3
engine = kNNEmbeddingEngine(model_path, kNN)

app = Flask(__name__, static_url_path = "")

# global variables
brokerURL = ''
outputs = []
timer = None
lock = threading.Lock()
counter = 0 

camera = None
cameraURL = ''

@app.errorhandler(400)
def not_found(error):
    return make_response(jsonify( { 'error': 'Bad request' } ), 400)

@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify( { 'error': 'Not found' } ), 404)

@app.route('/admin', methods=['POST'])
def admin():    
    if not request.json:
        abort(400)
    
    configObjs = request.json
    handleConfig(configObjs)    
        
    return jsonify({ 'responseCode': 200 })


@app.route('/notifyContext', methods = ['POST'])
def notifyContext():
    print("=============notify=============")

    if not request.json:
        abort(400)
    	
    objs = readContextElements(request.json)

    print(objs)

    handleNotify(objs)
    
    return jsonify({ 'responseCode': 200 })


def element2Object(element):
    ctxObj = {}
    
    ctxObj['entityId'] = element['entityId'];
    
    ctxObj['attributes'] = {}  
    if 'attributes' in element:
        for attr in element['attributes']:
            ctxObj['attributes'][attr['name']] = {'type': attr['type'], 'value': attr['value']}   
    
    ctxObj['metadata'] = {}
    if 'domainMetadata' in element:    
        for meta in element['domainMetadata']:
            ctxObj['metadata'][meta['name']] = {'type': meta['type'], 'value': meta['value']}
    
    return ctxObj

def object2Element(ctxObj):
    ctxElement = {}
    
    ctxElement['entityId'] = ctxObj['entityId'];
    
    ctxElement['attributes'] = []  
    if 'attributes' in ctxObj:
        for key in ctxObj['attributes']:
            attr = ctxObj['attributes'][key]
            ctxElement['attributes'].append({'name': key, 'type': attr['type'], 'value': attr['value']})
    
    ctxElement['domainMetadata'] = []
    if 'metadata' in ctxObj:    
        for key in ctxObj['metadata']:
            meta = ctxObj['metadata'][key]
            ctxElement['domainMetadata'].append({'name': key, 'type': meta['type'], 'value': meta['value']})
    
    return ctxElement

def readContextElements(data):
    print(data)

    ctxObjects = []
    
    for response in data['contextResponses']:
        if response['statusCode']['code'] == 200:
            ctxObj = element2Object(response['contextElement'])
            ctxObjects.append(ctxObj)
    
    return ctxObjects

def handleNotify(contextObjs):
    for ctxObj in contextObjs:
        processInputStreamData(ctxObj)

def processInputStreamData(obj):
    print('===============receive context entity====================')
    print(obj)
    
    entityId = obj['entityId']
    if entityId['type'] == 'Camera':
        getCameraURL(obj)
    elif entityId['type'] == 'Pushbutton':
        doTraining(obj)

def handleConfig(configurations):  
    global brokerURL
    global num_of_outputs  
    for config in configurations:        
        if config['command'] == 'CONNECT_BROKER':
            brokerURL = config['brokerURL']
        if config['command'] == 'SET_OUTPUTS':
            outputs.append({'id': config['id'], 'type': config['type']})
    
def handleTimer():
    global timer

    # # publish the counting result
    # entity = {}       
    # entity['id'] = "result.01"
    # entity['type'] = "Result"
    # entity['counter'] = counter    
     
    # publishResult(entity)
        
    timer = threading.Timer(10, handleTimer)
    timer.start()


def publishResult(result):
    resultCtxObj = {}
        
    resultCtxObj['entityId'] = {}
    resultCtxObj['entityId']['id'] = result['id']
    resultCtxObj['entityId']['type'] = result['type']        
    resultCtxObj['entityId']['isPattern'] = False    
    
    resultCtxObj['attributes'] = {}
    resultCtxObj['attributes']['counter'] = {'type': 'integer', 'value': result['counter']}

    # publish the real time results as context updates    
    updateContext(resultCtxObj)

def updateContext(ctxObj):
    global brokerURL
    if brokerURL == '':
        return
        
    ctxElement = object2Element(ctxObj)
    
    updateCtxReq = {}
    updateCtxReq['updateAction'] = 'UPDATE'
    updateCtxReq['contextElements'] = []
    updateCtxReq['contextElements'].append(ctxElement)

    headers = {'Accept' : 'application/json', 'Content-Type' : 'application/json'}
    response = requests.post(brokerURL + '/updateContext', data=json.dumps(updateCtxReq), headers=headers)
    if response.status_code != 200:
        print('failed to update context')
        print(response.text)

def getCameraURL(entityObj):
    global camera, cameraURL
    
    camera = entityObj    
    if 'attributes' in entityObj:
        attributes = entityObj['attributes']
        if 'url' in attributes:
            cameraURL = attributes['url']['value'] 

    print("SET camera URL = %s" % (cameraURL))

def doTraining(event):
    global cameraURL
    
    if cameraURL == '':
        print("the camera URL is not set yet")
        return
    
    print("camera URL %s" % (cameraURL))
    
    lock.acquire()
    
    global counter    
    counter = counter + 1
            
    response = requests.get(cameraURL)
    img = Image.open(BytesIO(response.content))
    
    emb = engine.DetectWithImage(img)
    
    if counter < 10:
        engine.addEmbedding(emb, "defect")    
        print("trained with the captured image")                        
    else:
        result = engine.kNNEmbedding(emb)
        print("detected result %s" %(result))              

    lock.release()
                             
if __name__ == '__main__':
    handleTimer()    
   
    myport = int(os.environ['myport'])

    print(myport)

    myCfg = os.environ['adminCfg']
    adminCfg = json.loads(myCfg)
    print(myCfg)
    handleConfig(adminCfg)         

    app.run(host='0.0.0.0', port=myport)
    
    timer.cancel()
    
