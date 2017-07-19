__author__ = 'jonhall'
#
## Export invoice data into billing report.html
## Place APIKEY & Username in config.ini
## or pass via commandline  (example: bmx-billing-report.html.py -u=userid -k=apikey)
##

import SoftLayer, configparser,csv,logging,time, os
from flask import Flask, render_template, request, flash, redirect, url_for, send_file, Blueprint

app = Flask(__name__)
app.secret_key = 'sdfsdf23423sdfsdfsdf'

def getDescription(categoryCode, detail):
    for item in detail:
        if 'categoryCode' in item:
            if item['categoryCode']==categoryCode:
                return item['description']
    return "Not Found"

@app.route('/invoices', methods=["GET","POST"])
def getInvoice():
    if request.method == "POST":
        # define global variable for client
        global client, invoiceDate1, invoiceDate2
        # Get POST DATA FROM FORM
        invoiceDate1 = request.form['invoiceDate1']
        invoiceDate2 = request.form['invoiceDate2']
        client = SoftLayer.Client(username=request.form['username'], api_key=request.form['apiKey'])
        return redirect(url_for('getInvoice'))


    # Build Filter for Invoices
    InvoiceList = client['Account'].getInvoices(filter={
        'invoices': {
            'createDate': {
                'operation': 'betweenDate',
                'options': [
                    {'name': 'startDate', 'value': [invoiceDate1 + " 0:0:0"]},
                    {'name': 'endDate', 'value': [invoiceDate2 + " 23:59:59"]}

                ]
            },
            'typeCode': {
                'operation': 'in',
                'options': [
                    {'name': 'data', 'value': ['RECURRING']}
                ]
            },
        }
    })
    return render_template('invoices.html', entries=InvoiceList)

def getTopLevelDetail(item):
    #Get Detail From Rrecord

    billingItemId = item['billingItemId']
    print ("Getting BillingItemID %s" % billingItemId)
    category = item["categoryCode"]

    if 'hostName' in item:
        hostName = item['hostName'] + "." + item['domainName']
    else:
        hostName = "Unnamed Device"

    recurringFee = float(item['totalRecurringAmount'])

    # IF Monthly calculate hourly rate and total hours
    if 'hourlyRecurringFee' in item:
        instanceType = "Hourly"
        associated_children = ""
        while associated_children is "":
            try:
                time.sleep(1)
                associated_children = client['Billing_Invoice_Item'].getNonZeroAssociatedChildren(id=item['id'],
                                                                                                  mask="hourlyRecurringFee")
            except SoftLayer.SoftLayerAPIError as e:
                logging.warning("getNonZeroAssociatedChildren(): %s, %s" % (e.faultCode, e.faultString))
                time.sleep(5)
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
        billing_detail = ""
        while billing_detail is "":
            try:
                time.sleep(1)
                billing_detail = client['Billing_Invoice_Item'].getChildren(id=item['id'],
                                                                            mask="description,categoryCode,product")
            except SoftLayer.SoftLayerAPIError as e:
                logging.warning("%s, %s" % (e.faultCode, e.faultString))

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
    row = {'BillingItemId': billingItemId,
           'InstanceType': instanceType,
           'hostName': hostName,
           'Category': category,
           'Description': description,
           'Hours': hours,
           'Hourly_Rate': round(hourlyRecurringFee, 3),
           'RecurringCharge': round(recurringFee, 2)
           }
    return row

@app.route('/')
def input():
    return render_template('input.html')

@app.route('/bmxbillingreport/display')
def display(row):
    return render_template('display.html', row=row)

@app.route('/runreport/<invoiceID>', methods=["POST"])
def runreport(invoiceID):
    outputname = 'invoice-'+str(invoiceID)+'.csv'
    outfile = open(outputname, 'w')
    csvwriter = csv.writer(outfile, delimiter='\t', quotechar='"', quoting=csv.QUOTE_ALL)

    fieldnames = ['Invoice_Number', 'Invoice_Date', 'BillingItemId', 'InstanceType', 'hostName', 'Category', 'Description',
                 'Hours', 'Hourly_Rate', 'RecurringCharge', 'InvoiceTotal']

    csvwriter = csv.DictWriter(outfile, delimiter=',', fieldnames=fieldnames)
    csvwriter.writerow(dict((fn, fn) for fn in fieldnames))

    # GET Detailed Billing Invoice Detail
    Billing_Invoice = client['Billing_Invoice'].getObject(id=invoiceID,
        mask="invoiceTopLevelItems, invoiceTopLevelItems.totalRecurringAmount, invoiceTotalAmount, invoiceTopLevelItemCount, invoiceTotalRecurringAmount")

    if Billing_Invoice['invoiceTotalAmount'] > "0":
        flash("Get Billing Item Detail for Invoice %s" % invoiceID)

        # Get Invoice Total Amounts
        invoiceTotalAmount = float(Billing_Invoice['invoiceTotalAmount'])

        # ITERATE THROUGH TOP LEVEL ITEMS ON THE INVOICE
        for item in Billing_Invoice['invoiceTopLevelItems']:
            row = getTopLevelDetail(item)
            row['Invoice_Number'] = invoiceID
            row['Invoice_Date'] = Billing_Invoice['createDate'][0:10]
            row['InvoiceTotal'] = invoiceTotalAmount
            csvwriter.writerow(row)
    outfile.close()
    return send_file(outputname, mimetype="text/csv", attachment_filename=os.path.basename(outputname),
                     as_attachment=True)

@app.route('/invoiceinfo/<invoiceID>')
def invoiceinfo(invoiceID):
    #Get Detail Invoice

    invoice = client['Billing_Invoice'].getObject(id=invoiceID,mask="accountId, id, invoiceTotalAmount, companyName, closedDate, itemCount")
    print (invoice)
    return render_template('invoice-info.html', entry=invoice)


if __name__ == "__main__":
    app.run(host='0.0.0.0')
