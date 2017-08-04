__author__ = 'jonhall'
#
## Generate Invoice Billing Report from TopLevel data from Recurring Invoices.
##

import SoftLayer,logging,time,configparser,redis,os
import pandas as pd
from flask import Flask, render_template, make_response, request, redirect, url_for, Blueprint,session, jsonify
from flask_session import Session
from celery import Celery



bp = Blueprint('bmxbillingreport', __name__,
                        template_folder='templates',
                        static_folder='static',
                        url_prefix='/bmxbillingreport')

app = Flask(__name__)
app.secret_key = 'sdfsdf23423%12(&sdfsdfsdf'


# Establish Redis to store session data
SESSION_TYPE = 'redis'
SESSION_REDIS = redis.Redis(os.environ['SESSION_REDIS'])
app.config.from_object(__name__)
Session(app)

# Establish Celery & Configure to use Redis Broker & Queing
app.config['SECRET_KEY'] = "cloud2017"
app.config['CELERY_BROKER_URL'] = os.environ['CELERY_BROKER_URL']
app.config['CELERY_RESULT_BACKEND'] = os.environ['CELERY_RESULT_BACKEND']


celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)



def getDescription(categoryCode, detail):
    for item in detail:
        if 'categoryCode' in item:
            if item['categoryCode']==categoryCode:
                return item['description']
    return "Not Found"

@bp.route('/invoices', methods=["GET","POST"])
def getInvoice():
    if request.method == "POST":
        username= request.form['username']
        apiKey = request.form['apiKey']
        if username=="demo":
            username = os.environ['username']
            apiKey = os.environ['apikey']

        startdate = request.form['startdate'] + " 00:00:00"
        enddate = request.form['enddate'] + " 23:59:59"
        session['username']=username
        session['apiKey']=apiKey
        session['startdate']=startdate
        session['enddate']=enddate


    client = SoftLayer.Client(username=session.get('username','not set'), api_key=session.get('apiKey','not set'), timeout=60)
    # Build Filter for Invoices
    try:
        InvoiceList = client['Account'].getInvoices(filter={
            'invoices': {
                'createDate': {
                    'operation': 'betweenDate',
                    'options': [
                        {'name': 'startDate', 'value': [startdate]},
                        {'name': 'endDate', 'value': [enddate]}

                    ]
                },
                'typeCode': {
                    'operation': 'in',
                    'options': [
                        {'name': 'data', 'value': ['RECURRING']}
                    ]
                },
            }
        }, mask="id, accountId, companyName, createDate, statusCode, invoiceTotalAmount")
    except SoftLayer.SoftLayerAPIError as e:
        logging.warning("getInvoices(): %s, %s" % (e.faultCode, e.faultString))
        return render_template('error.html', faultCode=e.faultCode, faultString=e.faultString)

    return render_template('invoices.html', entries=InvoiceList)

def getTopLevelDetail(item,username,apiKey):
    #Get Detail From Record

    client = SoftLayer.Client(username=username, api_key=apiKey)

    billingItemId = item['billingItemId']
    category = item["categoryCode"]

    if 'hostName' in item:
        hostName = item['hostName'] + "." + item['domainName']
    else:
        hostName = "Unnamed Device"

    recurringFee = float(item['totalRecurringAmount'])

    # IF Monthly calculate hourly rate and total hours
    if 'hourlyRecurringFee' in item:
        instanceType = "Hourly"
        try:
            time.sleep(0.2)
            associated_children = client['Billing_Invoice_Item'].getNonZeroAssociatedChildren(id=item['id'],
                                                                                              mask="hourlyRecurringFee")
        except SoftLayer.SoftLayerAPIError as e:
            logging.warning("getNonZeroAssociatedChildren(): %s, %s" % (e.faultCode, e.faultString))
            row = {}
            return row

        # calculate total hourlyRecurringFree from associated childrent
        hourlyRecurringFee = float(item['hourlyRecurringFee']) + sum(
            float(child['hourlyRecurringFee']) for child in associated_children)
        if hourlyRecurringFee > 0:
            hours = round(float(recurringFee) / hourlyRecurringFee)
        else:
            hours = 0
    else:
        instanceType = "Monthly/Other"
        hourlyRecurringFee = 0
        hours = 0

    if category == "storage_service_enterprise" or category == "performance_storage_iscsi":
        try:
            billing_detail = client['Billing_Invoice_Item'].getChildren(id=item['id'],
                                                                        mask="description,categoryCode,product")
        except SoftLayer.SoftLayerAPIError as e:
            logging.warning("%s, %s" % (e.faultCode, e.faultString))
            row = {}
            return row

        if category == "storage_service_enterprise":
            iops = getDescription("storage_tier_level", billing_detail)
            storage = getDescription("performance_storage_space", billing_detail)
            snapshot = getDescription("storage_snapshot_space", billing_detail)
            if snapshot == "Not Found":
                description = storage + " " + iops + " "
            else:
                description = storage + " " + iops + " with " + snapshot
        else:
            iops = getDescription("performance_storage_iops", billing_detail)
            storage = getDescription("performance_storage_space", billing_detail)
            description = storage + " " + iops
    else:
        description = item['description']
        description = description.replace('\n', " ")

    # BUILD CSV OUTPUT & WRITE ROW
    row = {'billingItemId': billingItemId,
           'productGroup': item['topLevelProductGroupName'],
           'location': item['location']['name'],
           'instanceType': instanceType,
           'hostName': hostName,
           'category': category,
           'description': description,
           'hours': hours,
           'hourlyRate': round(hourlyRecurringFee, 3),
           'recurringCharge': round(recurringFee, 2)
           }
    return row

@bp.before_request
def session_management():
    # make the session last indefinitely until it is cleared
    session.permanent = True

@bp.route('/', methods=["GET","POST"])
def input():
    # reset the session data
    session.clear()
    return render_template('input.html')

@bp.route('/bmxbillingreport/display')
def display(row):
    return render_template('display.html', row=row)

@bp.route('/detail', methods=["GET","POST"] )
def detail():
    if request.method == "POST":
        session['results'] = request.json
        return redirect(url_for("bmxbillingreport.detail"))
    results= session.get('results', 'not set')
    return render_template('detail.html', detail=results)

@bp.route('/runreport/<invoiceID>', methods=["POST"])
def runreport(invoiceID):
    task = long_task.apply_async(kwargs={"username" :session.get('username', 'not set'), "apiKey": session.get('apiKey','not set'), "invoiceID": invoiceID})
    return jsonify({}), 202, {'Location': url_for('bmxbillingreport.taskstatus', task_id=task.id)}

@bp.route('/status/<task_id>')
def taskstatus(task_id):
    task = long_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        ## Job has not started yet
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }

    return jsonify(response)

@celery.task(bind=True)
def long_task(self,**kwargs):
    username = kwargs.pop('username')
    apiKey = kwargs.pop('apiKey')
    invoiceID = kwargs.pop('invoiceID')

    # Long Running Report gets top level items and builds report
    # Process runs using background Async tasks with Celery
    # sends updates to browser & notifies when complete

    self.update_state(state='PROGRESS',
                      meta={'current': 0, 'total': 1, 'status': "Getting invoice top level items."})

    client = SoftLayer.Client(username=username, api_key=apiKey)

    df=pd.DataFrame(
        {'billingItemId': pd.Series([], dtype='str'),
         'productGroup': pd.Series([],dtype='str'),
         'location': pd.Series([], dtype='str'),
         'instanceType': pd.Series([], dtype='str'),
         'hostName': pd.Series([], dtype='str'),
         'category': pd.Series([], dtype='str'),
         'description': pd.Series([], dtype='str'),
         'hours': pd.Series([], dtype='int'),
         'hourlyRate': pd.Series([], dtype='float'),
         'recurringCharge': pd.Series([], dtype='float'),
         'invoiceId': pd.Series([], dtype='str'),
         'invoiceDate': pd.Series([], dtype='str'),
         'invoiceTotal': pd.Series([], dtype='float')
         })


    # GET Detailed Billing Invoice Detail
    try:
        Billing_Invoice = client['Billing_Invoice'].getObject(id=invoiceID,
            mask="invoiceTopLevelItems, invoiceTopLevelItems.topLevelProductGroupName, invoiceTopLevelItems.location, invoiceTopLevelItems.totalRecurringAmount, invoiceTotalAmount, invoiceTopLevelItemCount, invoiceTotalRecurringAmount")
    except SoftLayer.SoftLayerAPIError as e:
        logging.warning("%s, %s" % (e.faultCode, e.faultString))
        message = ("Error: %s %s" % e.faultCode, e.faultString)
        self.update_state(state='Failure',
                          meta={'current': i, 'total': total, 'status': "Error: No results returned."})
        return

    i=0
    invoiceTotalAmount = float(Billing_Invoice['invoiceTotalAmount'])
    total=len(Billing_Invoice['invoiceTopLevelItems'])

    # ITERATE THROUGH TOP LEVEL ITEMS ON THE INVOICE

    for item in Billing_Invoice['invoiceTopLevelItems']:
        i=i+1
        row = getTopLevelDetail(item,username,apiKey)
        if 'billingItemId' not in row:
            self.update_state(state='Failure',
                meta={'current': i, 'total': total, 'status': "Error: No results returned."})
            return {'current': i, 'total': total, 'status': 'Error: No results returned.' }
        row['invoiceId'] = invoiceID
        row['invoiceDate'] = Billing_Invoice['createDate'][0:10]
        row['invoiceTotal'] = invoiceTotalAmount
        df= df.append(row, ignore_index=True)
        message = ("Retreived billingItemID %s" % (row["billingItemId"]))
        self.update_state(state='PROGRESS',
                          meta={'current': i, 'total': total, 'status': message})

    return {'current': i, 'total': total, 'status': 'All records received!', 'result': df.to_dict('records')}

@bp.route('/invoiceinfo/<invoiceID>')
def invoiceinfo(invoiceID):
    #Get Invoice Info
    client = SoftLayer.Client(username=session.get('username', 'not set'), api_key=session.get('apiKey', 'not set'), timeout=60)
    invoice = client['Billing_Invoice'].getObject(id=invoiceID,mask="accountId, id, invoiceTotalAmount, companyName, createDate, invoiceTopLevelItemCount")
    return render_template('invoice-info.html', entry=invoice)


app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
