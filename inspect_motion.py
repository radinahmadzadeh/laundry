from pathlib import Path
s=Path('orders/templates/home.html').read_text(encoding='utf-8-sig')
for key in ['.enter{','.breathe{','@keyframes','services-grid','service-card','class="panel']:
 print('\n---',key,'---')
 start=0;n=0
 while n<8:
  i=s.find(key,start)
  if i<0: break
  print(s[i:i+260].replace('\n',' ')[:260])
  start=i+1;n+=1
