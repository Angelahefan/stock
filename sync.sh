#!/bin/bash
# Deploy datapai-stock-be to EC2
rsync -avz --delete --progress \
  -e "ssh -i ~/.ssh/Linux-CodeCambat.pem" \
  --exclude .claude/ --exclude .git/ --exclude __pycache__/ --exclude .env \
  ~/git/datapai-stock-be/ \
  ec2-user@platform.datap.ai:/home/ec2-user/git/datapai-stock-be/
