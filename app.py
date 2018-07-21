from flask import Flask, render_template, request
import lithiumate_data_logger

f = open("test.txt", "w+")
f.write("got it")
f.close()
app = Flask(__name__)

# Show the page
@app.route('/')
def index():
	return render_template('index.html')

# Handle a request from the page for the list of WiFi networks
@app.route('/getWiFiList', methods=['GET'])
def getWiFiList():
	srvResp = 'Fail'
	if request.method == 'GET':
 		srvResp = lithiumate_data_logger.getWiFiList()
	return srvResp

# Handle a request from the page to select a WiFi network
@app.route('/postWiFiSrvc', methods=['POST'])
def postWiFiSrvc():
	srvResp = 'Fail'
	if request.method == 'POST':
		wiFiNet = request.form['wiFiNet']
		wiFiPassword = request.form['wiFiPassword']
  		srvResp = lithiumate_data_logger.postWiFiSrvc(wiFiNet, wiFiPassword)
	return srvResp

# Handle a request from the page to control the Pi
@app.route('/postControlSrvc', methods=['POST'])
def postControlSrvc():
	srvResp = 'Fail'
	if request.method == 'POST':
		ctrlDictJson = request.form['cd']
		srvResp = lithiumate_data_logger.postControlSrvc(ctrlDictJson)
	return srvResp

# Handle a request from the page to log data
@app.route('/postLogDataSrvc', methods=['POST'])
def postLogDataSrvc():
	srvResp = 'Fail'
	if request.method == 'POST':
		logDataStr = request.form['d']
 		srvResp = lithiumate_data_logger.postLogDataSrvc(logDataStr)
	return srvResp

# Handle a request from the page to reboot
@app.route('/getReboot', methods=['GET'])
def getReboot():
 	lithiumate_data_logger.getReboot()
	return 0

if __name__ == '__main__':
	app.run(debug=True, host='0.0.0.0')
