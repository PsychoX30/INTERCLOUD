#!/bin/bash
# Mass-complete verified NgodingPakeAI tasks
cd /app
grep -oP '^\s+.\s+\K[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' /app/memory/scripts/task_list.txt > /app/memory/scripts/task_ids.txt
total=$(wc -l < /app/memory/scripts/task_ids.txt)
echo "Total tasks to complete: $total"
n=0
while read -r id; do
  n=$((n+1))
  npx ngodingpakeai task start "$id" >> /app/memory/scripts/complete_log.txt 2>&1
  npx ngodingpakeai task complete "$id" >> /app/memory/scripts/complete_log.txt 2>&1
  echo "[$n/$total] $id" >> /app/memory/scripts/complete_progress.txt
done < /app/memory/scripts/task_ids.txt
echo "DONE ALL" >> /app/memory/scripts/complete_progress.txt
