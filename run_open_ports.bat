@echo off
setlocal

echo Configuring Windows Firewall inbound rules for Nickelfront...

netsh advfirewall firewall delete rule name="Nickelfront Frontend 5173" >nul 2>&1
netsh advfirewall firewall add rule name="Nickelfront Frontend 80" dir=in action=allow protocol=TCP localport=80 >nul 2>&1
netsh advfirewall firewall add rule name="Nickelfront Backend 8001" dir=in action=allow protocol=TCP localport=8001 >nul 2>&1
netsh advfirewall firewall add rule name="Nickelfront Flower 5555" dir=in action=allow protocol=TCP localport=5555 >nul 2>&1

echo Done. If rules were not created, run this file as Administrator.
endlocal
