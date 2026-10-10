🅿️ ParkSmart — Complete Project Workflow
Final project concept

IoT-enabled Smart Parking Management System with real-time monitoring, online reservation, QR validation, automatic gate control, parking-session tracking, billing, payment records, notifications, analytics and administration.

We have two sides:

                 PARKSMART
                    │
          ┌─────────┴─────────┐
          │                   │
      SOFTWARE             HARDWARE
          │                   │
 Flask + Database       ESP32 + IR + Servo

The hardware is assumed to be constructed. Our main work now is the software.

1. 👤 User Registration & Login

A new driver opens ParkSmart.

Register
   ↓
Name
Email
Password
Vehicle Number
   ↓
Account Created
   ↓
Login
   ↓
Driver Dashboard

Passwords are stored securely as hashes, not plain text.

There are two roles:

Driver
   ↓
Parking functions

Administrator
   ↓
Management functions
2. 🏠 Driver Dashboard

After login, the driver sees:

┌─────────────────────────────────────┐
│ 🅿️ PARKSMART                        │
│                                     │
│ Available: 2      Occupied: 2      │
│                                     │
│ 🟢 S01 AVAILABLE                    │
│ 🔴 S02 OCCUPIED                     │
│ 🟢 S03 AVAILABLE                    │
│ 🔴 S04 OCCUPIED                     │
│                                     │
│ [ RESERVE PARKING ]                 │
│ [ MY PARKING ]                      │
│ [ HISTORY ]                          │
└─────────────────────────────────────┘

The dashboard gets slot information from the database, which ultimately receives real-time information from the ESP32.

3. 📡 Hardware → Software Workflow

This is the core IoT part.

We have:

             ESP32
               │
      ┌────────┼────────┐
      ↓        ↓        ↓
    IR S1    IR S2    IR S3/S4
      │
      └──────────┬──────────┘
                 ↓
          Detect occupancy
                 ↓
              ESP32
                 ↓
          Serial / API
                 ↓
             Flask
                 ↓
             Database
                 ↓
          Web Dashboard

Our four sensors:

Slot	ESP32
S01	GPIO 32
S02	GPIO 33
S03	GPIO 25
S04	GPIO 26

Gate servo:

Servo → GPIO 27
4. 🅿️ Live Slot Detection

Suppose:

S1 = Free
S2 = Occupied
S3 = Free
S4 = Occupied

ESP32 sends the state.

Software updates:

Total = 4
Occupied = 2
Available = 2

Dashboard becomes:

🟢 S01
🔴 S02
🟢 S03
🔴 S04

Available Slots: 2

This happens continuously.

5. 📅 Reservation Workflow

The driver can reserve before arriving.

Driver
  ↓
Reserve Parking
  ↓
Select Date
  ↓
Select Arrival Time
  ↓
Select Departure Time
  ↓
System checks database
  ↓
Available slots displayed
  ↓
Driver chooses slot
  ↓
Enter vehicle number
  ↓
Confirm

Then:

Reservation Created
        ↓
Reservation ID
        ↓
QR Code Generated
        ↓
Saved in Database

Example:

Reservation ID: PS-20261006-0017
Slot: S02
Vehicle: TN XX XXXX
Time: 10:00–12:00
Status: CONFIRMED
6. 📱 QR Reservation

The QR code represents the reservation.

At the entrance:

Vehicle arrives
      ↓
QR validated
      ↓
Reservation exists?
   ┌──┴──┐
  YES    NO
   ↓      ↓
Validate  Normal
booking   parking
   ↓
Open gate

For the academic prototype, QR scanning can be demonstrated through a web-based scanner/simulation without buying dedicated scanning hardware.

7. 🚗 Vehicle Entry

There are two possibilities.

Reserved vehicle
QR/Reservation
      ↓
Validate
      ↓
Find reserved slot
      ↓
Open gate
      ↓
Vehicle enters
      ↓
IR sensor confirms occupancy
      ↓
Slot = OCCUPIED
      ↓
Entry time recorded
Normal/walk-in vehicle
Vehicle arrives
      ↓
Check available slots
      ↓
Find first suitable slot
      ↓
Assign slot
      ↓
Open gate
      ↓
Vehicle enters
      ↓
IR confirms
      ↓
Slot = OCCUPIED
8. 🚪 Gate Control

The Flask software sends a command to ESP32:

OPEN GATE
    ↓
ESP32
    ↓
Servo rotates
    ↓
Gate opens

After the configured period:

CLOSE GATE
    ↓
ESP32
    ↓
Servo rotates back

So the software controls the physical gate.

9. 🅿️ Vehicle Parking

After entering:

Vehicle → Assigned Slot
             ↓
        IR Sensor
             ↓
       Vehicle detected
             ↓
       Slot = OCCUPIED
             ↓
      Dashboard updates

The parking session records:

Vehicle
Slot
Entry Time
Status
10. 🚙 Vehicle Exit

When the vehicle leaves:

Vehicle leaves
      ↓
IR sensor detects vacancy
      ↓
Slot = AVAILABLE
      ↓
Exit time recorded
      ↓
Parking duration calculated

Example:

Entry = 10:15
Exit  = 12:20

Duration = 2h 05m
11. 💰 Automatic Billing

The software calculates:

Duration
   ↓
Pricing rules
   ↓
Parking fee

Example:

First hour       ₹20
Additional hour  ₹10

Duration = 2h 05m

Total = ₹30

Then:

Parking Session
      ↓
Bill Generated
      ↓
Payment
12. 💳 Payment

For our college project, payment is simulated, unless we later connect a real payment gateway.

Workflow:

Bill = ₹30
   ↓
[ PAY ₹30 ]
   ↓
Processing
   ↓
Payment Successful
   ↓
Transaction ID generated
   ↓
Status = PAID

Database stores:

Payment ID
Session ID
Amount
Transaction ID
Time
Status

We should explicitly call this a simulated payment module in the academic project unless an actual gateway is integrated.

13. 🧾 Digital Receipt

After payment:

Payment Successful
        ↓
Generate Receipt
        ↓
PDF

Receipt contains:

PARKSMART
Parking Receipt

Vehicle
Slot
Entry
Exit
Duration
Parking Fee
Transaction ID
Payment Status

User can:

[ DOWNLOAD PDF ]
[ PRINT ]
14. 📧 Email

Once email configuration is added:

Reservation
    ↓
Confirmation Email

Vehicle Exit
    ↓
Bill Generated
    ↓
Receipt PDF
    ↓
Email

So the driver can receive:

Your parking session has ended.
Total amount: ₹30.
Receipt attached.

15. 📜 Parking History

Driver can open:

My Parking History

and see:

Date	Slot	Entry	Exit	Fee	Status
Oct 6	S02	10:15	12:20	₹30	Paid
Oct 5	S01	14:10	15:30	₹30	Paid

This data comes directly from the database.

16. 👨‍💼 Admin Workflow

Admin has a completely different dashboard.

Admin Login
     ↓
Admin Dashboard

Admin can see:

Total Slots
Available
Occupied
Current Vehicles
Reservations
Revenue
System Status

And can manage:

Parking slots
Reservations
Parking sessions
Users
Payments
System logs
Gate
ESP32 status
17. 📊 Analytics

The system collects historical data.

Therefore we can calculate:

Today's Vehicles
Today's Revenue
Average Parking Duration
Peak Occupancy
Most Used Slot
Reservations

Example:

TODAY

Vehicles:       42
Reservations:   18
Revenue:        ₹1,240
Occupancy:      75%

Charts can show:

Vehicles per hour
Slot utilization
Daily revenue
Occupancy percentage
18. 🚨 Fault Monitoring

The software also monitors the system itself.

Example:

SYSTEM HEALTH

ESP32              🟢 ONLINE
Serial Connection   🟢 CONNECTED
IR Sensor 1         🟢 NORMAL
IR Sensor 2         🟢 NORMAL
IR Sensor 3         🟢 NORMAL
IR Sensor 4         🟢 NORMAL
Gate Servo          🟢 NORMAL
Database            🟢 NORMAL

If ESP32 disconnects:

🔴 ESP32 CONNECTION LOST

Attempting reconnection...

If a sensor fails:

⚠ Sensor 3 not responding

These events are stored in system logs.

19. 🗄️ Database — The Heart of the Software

Everything important is stored here.

                 DATABASE
                     │
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
     Users         Slots       Reservations
       │             │             │
       └─────────────┼─────────────┘
                     ↓
              Parking Sessions
                     │
              ┌──────┴──────┐
              ↓             ↓
          Payments      Notifications
                     │
                     ↓
                System Logs

So if you close the application and reopen it, the important records remain.

20. 🧪 Testing Workflow

We're not just testing the sensors.

We're testing the software system.

For example:

TC01 → Registration
TC02 → Login
TC03 → Invalid login
TC04 → Slot monitoring
TC05 → Reservation
TC06 → Duplicate reservation rejection
TC07 → Slot allocation
TC08 → Vehicle entry
TC09 → Vehicle exit
TC10 → Duration calculation
TC11 → Fee calculation
TC12 → Bill generation
TC13 → Payment
TC14 → PDF receipt
TC15 → Admin authorization
TC16 → Parking full
TC17 → Database persistence
TC18 → ESP32 communication failure

We'll eventually have both:

Manual functional testing + automated Pytest testing.

21. 🔄 Complete End-to-End Workflow

This is the single most important flow to remember for your viva:

                    USER
                     │
                     ▼
                REGISTER/LOGIN
                     │
                     ▼
              VIEW LIVE SLOTS
                     │
              ┌──────┴──────┐
              │             │
          RESERVE         WALK-IN
              │             │
              ▼             ▼
           QR CODE      CHECK SLOTS
              │             │
              └──────┬──────┘
                     ▼
               VEHICLE ARRIVES
                     │
                     ▼
              VALIDATE / ASSIGN
                     │
                     ▼
                 OPEN GATE
                     │
                     ▼
                 VEHICLE ENTERS
                     │
                     ▼
                IR SENSOR
                     │
                     ▼
              SLOT = OCCUPIED
                     │
                     ▼
              ENTRY TIME SAVED
                     │
                     ▼
                PARKING
                     │
                     ▼
               VEHICLE EXITS
                     │
                     ▼
                IR SENSOR
                     │
                     ▼
              SLOT = AVAILABLE
                     │
                     ▼
                EXIT TIME
                     │
                     ▼
             CALCULATE DURATION
                     │
                     ▼
              CALCULATE FEE
                     │
                     ▼
                 GENERATE BILL
                     │
                     ▼
                  PAYMENT
                     │
                     ▼
             TRANSACTION RECORDED
                     │
                     ▼
                PDF RECEIPT
                     │
                     ▼
              EMAIL NOTIFICATION
                     │
                     ▼
               PARKING HISTORY
                     │
                     ▼
                 ANALYTICS
22. 🔌 Hardware ↔ Software Boundary

This is particularly important for your project explanation.

Hardware is responsible for:
IR Sensors
   ↓
Physical detection

ESP32
   ↓
Read sensors
Control servo
Send/receive commands
Software is responsible for:
Flask
   ↓
Business logic

Database
   ↓
Permanent records

Web UI
   ↓
User interaction

Reservation
   ↓
Slot booking

Billing
   ↓
Fee calculation

Analytics
   ↓
Reports

Authentication
   ↓
Security

So your project isn't merely an Arduino project.

It is an IoT + Web + Database + Software Engineering system.