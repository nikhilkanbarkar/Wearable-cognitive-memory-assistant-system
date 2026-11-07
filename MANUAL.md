# Cognitive Assist — Operations & Code Manual

This manual explains environment setup, execution commands, database management, systemd services, dashboard usage, scheduler operation, and troubleshooting.

---

## 1. Environment Setup

### 1.1 Navigate to the Project Directory

```bash
cd /home/pi/FaceRecognitionSystem2
```

### 1.2 Activate the Python Virtual Environment

```bash
source /home/pi/FaceRecognitionSystem2/.venv/bin/activate
```

After activation, the terminal should display the `(.venv)` prefix.

### 1.3 Verify Python

```bash
which python
python --version
```

The Python executable should point to the project's virtual environment.

### 1.4 Check Project Files

```bash
cd /home/pi/FaceRecognitionSystem2
ls -la
```

Check whether the required scripts and directories exist before running commands that depend on them.

---

## 2. Running the Application

### 2.1 Run Face Recognition Manually

Activate the virtual environment and execute:

```bash
cd /home/pi/FaceRecognitionSystem2
source /home/pi/FaceRecognitionSystem2/.venv/bin/activate
python face_recognition.py
```

Press `Ctrl+C` to stop the manually launched application.

**Important:** If `face-recognition.service` is already running, stop it before launching another instance that uses the same camera or GPIO resources.

```bash
sudo systemctl stop face-recognition
```

After testing, start the service again if required:

```bash
sudo systemctl start face-recognition
```

### 2.2 Run the Web Dashboard Manually

If the dashboard supports execution as a Python module, run:

```bash
cd /home/pi/FaceRecognitionSystem2
source /home/pi/FaceRecognitionSystem2/.venv/bin/activate
python -m web_dashboard.app
```

Press `Ctrl+C` to stop the dashboard.

### 2.3 Check the Dashboard URL

If the helper script exists:

```bash
cd /home/pi/FaceRecognitionSystem2
./show_dashboard_url.sh
```

Open the displayed address in a browser on a device connected to the same local network.

---

## 3. Database Management

The documented SQLite database location is:

```text
database/recognition.db
```

The database contains recognition records and scheduled reminder information.

### 3.1 Initialise or Synchronise the Database

If the script supports the `--resync-people` argument, run:

```bash
cd /home/pi/FaceRecognitionSystem2
source /home/pi/FaceRecognitionSystem2/.venv/bin/activate
python database_setup.py --resync-people
```

This command is intended to synchronise registered people with the database.

Do not delete or recreate the database as a troubleshooting shortcut.

### 3.2 List Database Tables

```bash
cd /home/pi/FaceRecognitionSystem2
sqlite3 database/recognition.db ".tables"
```

### 3.3 Inspect the Database Schema

Inspect the recognition-events table:

```bash
sqlite3 database/recognition.db ".schema recognition_events"
```

Inspect the scheduled-messages table:

```bash
sqlite3 database/recognition.db ".schema scheduled_messages"
```

Inspect the people table:

```bash
sqlite3 database/recognition.db ".schema people"
```

### 3.4 View Recent Recognition Events

```bash
cd /home/pi/FaceRecognitionSystem2
sqlite3 database/recognition.db \
  "SELECT * FROM recognition_events ORDER BY id DESC LIMIT 5;"
```

### 3.5 View Scheduled Messages

```bash
cd /home/pi/FaceRecognitionSystem2
sqlite3 database/recognition.db \
  "SELECT id, scheduled_time, status FROM scheduled_messages ORDER BY scheduled_time;"
```

If SQLite reports that a table or column does not exist, inspect the actual schema before modifying the database.

### 3.6 Back Up the Database

If the project backup script supports the `--with-files` argument:

```bash
cd /home/pi/FaceRecognitionSystem2
./backup_database.sh --with-files
```

Check the script output to confirm the backup location.

Back up important records before performing database maintenance.

---

## 4. Systemd Service Management

The documented service names are:

- `face-recognition`
- `face-dashboard`

The face-recognition service runs the main application. The dashboard service runs the web interface.

### 4.1 Check Service Status

Check the face-recognition service:

```bash
sudo systemctl status face-recognition
```

Check the dashboard service:

```bash
sudo systemctl status face-dashboard
```

Check whether the services are active:

```bash
systemctl is-active face-recognition
systemctl is-active face-dashboard
```

### 4.2 Start a Service

Start face recognition:

```bash
sudo systemctl start face-recognition
```

Start the dashboard:

```bash
sudo systemctl start face-dashboard
```

### 4.3 Stop a Service

Stop face recognition:

```bash
sudo systemctl stop face-recognition
```

Stop the dashboard:

```bash
sudo systemctl stop face-dashboard
```

Stopping the dashboard should not stop face recognition when both applications are configured as separate services.

### 4.4 Restart a Service

Restart face recognition after modifying its code or configuration:

```bash
sudo systemctl restart face-recognition
```

Restart the dashboard after modifying its code or configuration:

```bash
sudo systemctl restart face-dashboard
```

### 4.5 View Live Logs

Monitor face-recognition logs:

```bash
sudo journalctl -u face-recognition -f
```

Monitor dashboard logs:

```bash
sudo journalctl -u face-dashboard -f
```

Press `Ctrl+C` to stop following the logs.

### 4.6 View Recent Logs

```bash
sudo journalctl -u face-recognition -n 150 --no-pager
```

```bash
sudo journalctl -u face-dashboard -n 150 --no-pager
```

### 4.7 Enable Services at Boot

Enable both services:

```bash
sudo systemctl enable face-recognition face-dashboard
```

If the dashboard should remain optional, enable only face recognition:

```bash
sudo systemctl enable face-recognition
sudo systemctl disable face-dashboard
```

### 4.8 Disable Automatic Startup

```bash
sudo systemctl disable face-recognition face-dashboard
```

Disabling a service prevents automatic startup at boot. It does not necessarily stop a service that is already running.

### 4.9 Modify Dashboard Service Settings

Open the systemd override editor:

```bash
sudo systemctl edit face-dashboard
```

For example, if the application supports a dashboard password environment variable, an override could contain:

```ini
[Service]
Environment="DASHBOARD_PASSWORD=replace-with-a-strong-password"
```

Save the file and apply the changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart face-dashboard
```

Only configure environment variables that the application actually supports. Do not commit passwords or secrets to version control.

---

## 5. Web Dashboard

The dashboard is intended to be accessed through a browser on the same local network as the Raspberry Pi.

### 5.1 Open the Dashboard

Use:

```text
http://<pi-ip>:5000
```

Replace `<pi-ip>` with the Raspberry Pi's current local IP address.

### 5.2 Dashboard Pages

The documented dashboard pages are:

| Page | Route | Purpose |
|---|---|---|
| Dashboard | `/` | Summary statistics and recent events |
| History | `/history` | Recognition history and filtering |
| Unknown Faces | `/unknown` | Review unknown-face records |
| People | `/people` | View registered people |
| Schedule | `/schedule` | Create and cancel audio reminders |

The exact functionality available on each page depends on the installed dashboard implementation.

### 5.3 Local Network Access

The dashboard can be accessed over a local network without internet access, provided the Raspberry Pi and the browser device can communicate with each other.

However, the documented scheduler implementation separately checks internet connectivity before accepting or processing scheduled reminders.

---

## 6. General Troubleshooting

### 6.1 Face Recognition Is Not Starting

Check the service status:

```bash
sudo systemctl status face-recognition
```

Inspect recent logs:

```bash
sudo journalctl -u face-recognition -n 150 --no-pager
```

Restart the service if appropriate:

```bash
sudo systemctl restart face-recognition
```

### 6.2 Dashboard Is Not Accessible

Check the service:

```bash
sudo systemctl status face-dashboard
```

Inspect its logs:

```bash
sudo journalctl -u face-dashboard -n 150 --no-pager
```

Confirm that the dashboard is listening on the expected port and that both devices can communicate over the local network.

### 6.3 Bluetooth Audio Is Not Working

Check the Bluetooth device:

```bash
bluetoothctl info <BLUETOOTH-MAC>
```

Replace `<BLUETOOTH-MAC>` with the actual Bluetooth device address.

Inspect the application logs:

```bash
sudo journalctl -u face-recognition -f
```

Look for audio initialisation or playback errors.

### 6.4 Camera Is Not Working

Inspect the face-recognition logs:

```bash
sudo journalctl -u face-recognition -n 150 --no-pager
```

Check the camera connection and application configuration.

### 6.5 System Clock Is Incorrect

Check the system clock and time synchronisation status:

```bash
timedatectl status
```

Enable NTP synchronisation when appropriate:

```bash
sudo timedatectl set-ntp true
```

This enables system time synchronisation through the configured time service. It does not guarantee successful synchronisation unless a suitable time source is reachable.

---

## 7. The Scheduler Feature — Deep Dive

The scheduler allows caregivers to create audio reminders that are intended to play automatically through the Raspberry Pi's configured Bluetooth audio output.

Because reminders may be important, verify the system clock, connectivity, scheduler status, and audio output instead of assuming that every saved reminder will be delivered.

### 7.1 Scheduler Components

The documented scheduling process involves three main components.

#### 1. Web Interface

Files:

```text
web_dashboard/app.py
web_dashboard/templates/schedule.html
```

The caregiver enters a message and selects a date and time.

According to the described implementation:

- The dashboard checks internet connectivity.
- The selected local time is converted to UTC.
- The task is saved in the SQLite database with status `PENDING`.

#### 2. Database

Table:

```text
scheduled_messages
```

The database stores scheduled tasks until they become due or are cancelled.

The documented implementation stores the scheduled time in UTC.

#### 3. Background Scheduler

Location:

```text
scheduler_worker in face_recognition.py
```

The described worker:

- Runs a background loop approximately every 15 seconds.
- Checks internet connectivity.
- Queries the database for due `PENDING` tasks.
- Updates a due task's status before submitting its message to the audio queue.
- Sends the message to the configured audio output.
- Repeats the message after a two-second delay, according to the described implementation.

The exact processing order and status-update behaviour should be verified against the installed source code.

### 7.2 Scheduler Workflow

```text
+--------------------------------+
| Caregiver opens Schedule page  |
+---------------+----------------+
                |
                v
+--------------------------------+
| Enter message and date/time    |
+---------------+----------------+
                |
                v
+--------------------------------+
| Is internet reachable?         |
+---------------+----------------+
                |
          +-----+-----+
          |           |
         No          Yes
          |           |
          v           v
+----------------+  +--------------------------+
| Show error     |  | Convert local time to UTC|
| Do not save    |  +-------------+------------+
+----------------+                |
                                  v
                     +--------------------------+
                     | Save task as PENDING     |
                     +-------------+------------+
                                   |
                                   v
                     +--------------------------+
                     | Scheduler checks tasks  |
                     | approximately every 15s |
                     +-------------+------------+
                                   |
                                   v
                     +--------------------------+
                     | Is internet reachable?  |
                     +-------------+------------+
                                   |
                             +-----+-----+
                             |           |
                            No          Yes
                             |           |
                             v           v
                   +----------------+  +----------------------+
                   | Log and wait   |  | Query due PENDING    |
                   | for connection |  | tasks in SQLite      |
                   +----------------+  +----------+-----------+
                                                  |
                                                  v
                                      +------------------------+
                                      | Is a task due?         |
                                      +-----------+------------+
                                                  |
                                            +-----+-----+
                                            |           |
                                           No          Yes
                                            |           |
                                            v           v
                                      +-----------+  +------------------+
                                      | Wait for  |  | Update task      |
                                      | next check|  | status atomically|
                                      +-----------+  +--------+---------+
                                                             |
                                                             v
                                                  +---------------------+
                                                  | Queue spoken message|
                                                  +----------+----------+
                                                             |
                                                             v
                                                  +---------------------+
                                                  | Play message as     |
                                                  | configured          |
                                                  +---------------------+
```

This flowchart represents the described implementation. Verify the actual source code to confirm the precise sequence and error-handling behaviour.

### 7.3 Why Does the Scheduler Require Internet?

The described implementation checks internet access using a connection attempt similar to:

```python
socket.create_connection(("8.8.8.8", 53))
```

The stated reason for this requirement is to help ensure that the Raspberry Pi's system clock is accurate.

A Raspberry Pi without a battery-backed real-time clock (RTC) may not retain accurate wall-clock time after a complete power loss. Network Time Protocol (NTP) can synchronise the clock when a suitable network and time source are available.

For example:

- Caregiver-selected time: `2:00 PM IST`
- IST offset: `UTC+05:30`
- Equivalent UTC time: `08:30 UTC`

The application stores the scheduled time in UTC so that comparisons can be made consistently.

**Important distinctions:**

- An internet connection does not automatically prove that the system clock has synchronised.
- NTP requires a configured time service and a reachable time source.
- A failed connection to `8.8.8.8:53` does not necessarily mean every possible network route is unavailable.
- Requiring internet for scheduling is an implementation choice, not a fundamental requirement of local scheduling. A reliable RTC or another suitable offline time strategy can support local scheduling without internet.

### 7.4 What Happens When the Pi Is Offline?

According to the described implementation:

1. The dashboard rejects new scheduling requests.
2. The dashboard displays an error.
3. The scheduler worker pauses processing while its connectivity check fails.
4. The worker logs a message similar to:

```text
[SCHEDULER] No internet connection. Waiting to sync time...
```

5. The worker resumes checking after connectivity returns.

Do not assume that a reminder will be delivered immediately after reconnection. Check the clock, task status, service logs, and audio output.

### 7.5 Task Statuses

The documented statuses are:

| Status | Meaning |
|---|---|
| `PENDING` | The task is waiting to be processed |
| `COMPLETED` | The worker has claimed or processed the task according to the implementation |
| `CANCELLED` | The task was cancelled before processing |

**Important:** If the implementation updates the status to `COMPLETED` before submitting the audio, that status does not prove the reminder was actually played or heard.

### 7.6 Schedule a Reminder

1. Open the dashboard:

   ```text
   http://<pi-ip>:5000
   ```

2. Navigate to the Schedule page:

   ```text
   /schedule
   ```

3. Select the date and time.

4. Enter the reminder message.

   Example:

   ```text
   It is time to take your medication.
   ```

5. Click **Schedule Message**.

6. Confirm that the task appears in the task history with status `PENDING`.

7. Monitor the face-recognition service logs:

   ```bash
   sudo journalctl -u face-recognition -f
   ```

8. After the scheduled time, refresh the dashboard and inspect the task status.

Example log messages from the described implementation:

```text
[SCHEDULER] Executing task #1: It is time to take your medication.
[VOICE] It is time to take your medication.
[VOICE] It is time to take your medication.
```

The exact log messages depend on the installed implementation.

Verify audible output directly. Logs alone cannot confirm that the user heard the reminder.

### 7.7 Scheduler Troubleshooting Flowchart

```text
+--------------------------------+
| Reminder did not play          |
+---------------+----------------+
                |
                v
+--------------------------------+
| Is face-recognition service    |
| running?                      |
+---------------+----------------+
                |
          +-----+-----+
          |           |
         No          Yes
          |           |
          v           v
+----------------+  +-------------------------+
| Start service  |  | Check scheduler logs     |
| and inspect    |  +------------+------------+
| errors         |               |
+----------------+               v
                    +-------------------------+
                    | Internet check failing? |
                    +------------+------------+
                                 |
                           +-----+-----+
                           |           |
                          Yes          No
                           |           |
                           v           v
                +----------------+  +-------------------------+
                | Check network  |  | Inspect task status     |
                | and system time|  +------------+------------+
                +----------------+               |
                                                 v
                                   +---------------------------+
                                   | Is task still PENDING?    |
                                   +-------------+-------------+
                                                 |
                                           +-----+-----+
                                           |           |
                                          Yes          No
                                           |           |
                                           v           v
                                  +----------------+  +---------------------+
                                  | Check UTC time |  | Check Bluetooth,     |
                                  | and worker     |  | audio logs, and task |
                                  | execution      |  | status-update order  |
                                  +----------------+  +---------------------+
```

### 7.8 Check Internet Connectivity

Run this Python test:

```bash
python - <<'PY'
import socket

try:
    with socket.create_connection(("8.8.8.8", 53), timeout=3):
        print("Connection to 8.8.8.8:53 succeeded")
except OSError as exc:
    print(f"Connection failed: {exc}")
PY
```

This checks the specified destination and port only. It is not a complete test of every internet connection.

### 7.9 Check System Time

Run:

```bash
timedatectl status
```

If appropriate, enable NTP:

```bash
sudo timedatectl set-ntp true
```

Check the status again:

```bash
timedatectl status
```

Confirm that the date, time, timezone, and synchronisation status are correct.

### 7.10 Inspect Scheduled Tasks

Run:

```bash
cd /home/pi/FaceRecognitionSystem2
sqlite3 database/recognition.db \
  "SELECT id, scheduled_time, status FROM scheduled_messages ORDER BY scheduled_time;"
```

To include the reminder text:

```bash
sqlite3 database/recognition.db \
  "SELECT id, scheduled_time, message, status FROM scheduled_messages ORDER BY scheduled_time;"
```

The documented implementation stores the scheduled time in UTC. For example, `08:30 UTC` corresponds to `14:00 IST` on the same date.

If the query fails, inspect the installed table schema:

```bash
sqlite3 database/recognition.db ".schema scheduled_messages"
```

### 7.11 Force a Controlled Scheduler Test

**Warning:** This procedure changes a database record. Use only a disposable test reminder. Do not modify a real medication or safety-related reminder.

First, inspect the selected task. Replace `1` with the ID of a test task:

```bash
cd /home/pi/FaceRecognitionSystem2
sqlite3 database/recognition.db \
  "SELECT id, scheduled_time, message, status
   FROM scheduled_messages
   WHERE id = 1;"
```

Confirm that the task is a test task and its status is `PENDING`.

Set its scheduled time to one minute ago:

```bash
sqlite3 database/recognition.db \
  "UPDATE scheduled_messages
   SET scheduled_time = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-1 minute')
   WHERE id = 1
     AND status = 'PENDING';"
```

Monitor the service logs:

```bash
sudo journalctl -u face-recognition -f
```

If the scheduler is running, connectivity is available, and audio is configured correctly, the worker should detect the due task during a subsequent check, normally within approximately 15 seconds.

Verify both the resulting database status and the actual audio output.

### 7.12 Check Bluetooth Audio

Inspect the Bluetooth device:

```bash
bluetoothctl info <BLUETOOTH-MAC>
```

Replace `<BLUETOOTH-MAC>` with the actual device address.

Inspect recent application logs:

```bash
sudo journalctl -u face-recognition -n 200 --no-pager
```

Look for Bluetooth initialisation, audio-output selection, and playback errors.

### 7.13 Task Is `COMPLETED`, but No Sound Was Heard

The described implementation updates the task status before sending the message to the audio queue.

Consequently, `COMPLETED` may mean that the worker claimed the task rather than confirming successful playback.

Check:

1. Whether Bluetooth is connected.
2. Whether the expected audio output is selected.
3. Whether the audio queue accepted the message.
4. Whether the service logs show playback errors.
5. Whether the scheduler updates the task status before or after playback.

Do not assume that a completed database status guarantees audible delivery.

---

## 8. Operational and Safety Notes

- Back up the database and associated files before maintenance.
- Use disposable test reminders when testing scheduler behaviour.
- Keep the face-recognition service and dashboard separate where possible.
- The locally hosted dashboard does not inherently require internet access, but the described scheduler implementation checks internet connectivity.
- Verify the system clock before relying on scheduled reminders.
- Test behaviour after power loss, network loss, Bluetooth disconnection, and service restart.
- For medication reminders or other critical alerts, use a secondary alerting method and validate the complete system under realistic failure conditions.

A scheduler that stores a reminder successfully is not necessarily a scheduler that guarantees delivery. The database, clock, worker, audio path, and user feedback must all be validated.



````markdown
## Finding the Bluetooth MAC Address

Follow these steps to find the MAC address of a Bluetooth device using the Raspberry Pi terminal.

### Step 1: Open Bluetooth Control

Run the following command in the Raspberry Pi terminal:

```bash
bluetoothctl
````

### Step 2: Enable Bluetooth

Enter these commands inside `bluetoothctl`:

```text
power on
agent on
default-agent
```

### Step 3: Scan for Bluetooth Devices

Put the earbuds or headphones into pairing mode and execute:

```text
scan on
```

Wait for the device to appear. Example:

```text
[NEW] Device 0D:B0:21:9E:9D:51 Noise Buds VS102
```

The MAC address is the hexadecimal value following `Device`.

### Step 4: List Discovered Devices

```text
devices
```

Example output:

```text
Device 0D:B0:21:9E:9D:51 Noise Buds VS102
Device 12:11:67:29:5C:E2 M3
```

Identify the required device by its name and note its MAC address.

### Step 5: Verify Device Information

Replace the example MAC address with the address of your device:

```text
info 0D:B0:21:9E:9D:51
```

Check these fields:

* `Name`: Bluetooth device name.
* `Paired`: Whether the device has been paired.
* `Trusted`: Whether the Raspberry Pi trusts the device.
* `Connected`: Whether the device is currently connected.
* `UUID: Audio Sink`: Indicates support for Bluetooth audio output.

### Step 6: Stop Scanning

```text
scan off
```

### Step 7: Exit Bluetooth Control

```text
exit
```

### Step 8: Pair and Connect the Device (If Required)

If the device is not already paired, put it into pairing mode and enter these commands inside `bluetoothctl`:

```text
pair DEVICE_MAC
trust DEVICE_MAC
connect DEVICE_MAC
```

Replace `DEVICE_MAC` with the actual MAC address.

If the device is already paired and trusted but disconnected, use:

```text
connect DEVICE_MAC
```

Verify the connection:

```text
info DEVICE_MAC
```

Expected status:

```text
Paired: yes
Trusted: yes
Connected: yes
```

**Note:** A MAC address alone does not guarantee that an unpaired device can connect. Initial pairing may require pairing mode and additional confirmation.

### Known Bluetooth Device MAC Addresses

| Device Name      | MAC Address         |
| ---------------- | ------------------- |
| Noise Buds VS102 | `0D:B0:21:9E:9D:51` |
| M3               | `12:11:67:29:5C:E2` |

**Important:** Use the MAC address corresponding to the intended audio device when configuring `bluetooth_audio.py`.

```
```
