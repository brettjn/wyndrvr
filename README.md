# wyndrvr
Latency and Bandwith Utility

I will describe the server and client functionality

(note we are using UDP sockets for this implemetation)

Server

When started the server will look for the existence of a ~/.wyndrvr/config file.  If found it will read these settings:

bind_addr (IP address for servers socket)
bind_port (port of server socket)

port_ranges                 (a list of beginning and ending ranges of ports that can be used for client connections)
connection_parallelibility *(an enum of type SINGLE, THREAD, PROCESS)
port_parallelability        (an enum of type SINGLE, THREAD, PROCESS)

incoming_blocking_level     (0=no blocking when reading the socket, positive=number of microseconds to block for)
incoming_sleep              (0=no sleep in incoming loop, otherwise microseconds of sleep)

max_send_time               (maximum microseconds of time spent sending packets, if more are available to send, before continuing on 
                             with the server commuincation loop)
send_sleep                **(0=no sleep in send loop, otherwise microsends of sleep)

heartbeat_rate              (minimum number of microseconds before heartbeat exchange)
adjustment_delay            (minimum microseconds of time in between adjusting transmission rate)
flow_control_rate           (this integer divides adjustment delay to get the minimum amount of time in between sending flow control 
                             packets)

* indicates whether this part of the program operates as a single process, or is multi-threaded, or uses processes.
** note with single threaded port handling there will be only one sleep in the communicaton loop as the same loop will handle both
incoming and outgoing packets so we can just use the sum of both sleeps

wyndrvr.py accepts these argument
--server [[addr]:[port]]   (bind address and port, if either is left off the config file values will be used otherwise
                            defaults will be 0.0.0.0 and 6711)
[[addr]:[port]]            (if used without the --server option wyndrvr will load up in client mode and the addr/port will
                            be that of the server)

When the server gets a connection it will print to stdout the address and port of the client, it will also send back to the client the three port addresses for it to connect to, one for a control connection, and one for uploading data and one for downloading data. The server will keep track of the ports in use which are selected from the port_ranges.  The server will resend the three port numbers back to the client every adjustment_delay seconds until it receives a heartbeat signal on all three of the ports opened up.                           

