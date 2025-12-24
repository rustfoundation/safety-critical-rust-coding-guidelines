#!/bin/bash

./make.py
if [ $? -eq "0" ];then
  echo "FLS is up to date"
  exit 0 # No error, no update required
else
  grep -q "ERROR: The FLS specification has changed since the lock file was created:" test.txt
  OUTOFDATE=$?
  grep -q "Found differences between live FLS data and lock file affecting 0 guidelines" test.txt
  ZEROAFFECTED=$?

  if [ $OUTOFDATE -eq "0" ]; then
    if [ $ZEROAFFECTED -eq "0" ]; then
      ./make.py --update-spec-lock-file
      rm test.txt
      echo 'true' >> "$CAN_AUTOMATICALLY_UPDATE"
      exit 1 # Can be updated automatically
    else
      ./make.py --update-spec-lock-file
      rm test.txt
      exit 2 # Guidelines need human review
    fi
  fi
fi

rm test.txt
exit 3 # Other build error not related to FLS
