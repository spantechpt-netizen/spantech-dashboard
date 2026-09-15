import re, base64, pathlib, markdown, html as H

HERE = pathlib.Path(__file__).resolve().parent
root = HERE.parent
src  = (root/"README.md").read_text(encoding="utf-8")

# strip masthead (h1 + subtitle + meta block up to first ---)
body_md = src.split("---",1)[1].split("\n---\n",1)[1].strip()

md = markdown.Markdown(extensions=["tables","fenced_code","attr_list","sane_lists"])
htmlbody = md.convert(body_md)

# inline drawings as scoped data-URI images
caps = {
 "DWG-01-general-arrangement":"DWG-01 · الترتيب العام — مسقط أفقي وواجهة أمامية",
 "DWG-02-cylinder-section":"DWG-02 · قطاع طولي في السلندر",
 "DWG-03-gripper":"DWG-03 · قامطة الودج",
 "DWG-04-nose-yoke":"DWG-04 · حدوة المقدمة",
 "DWG-05-crossbeam":"DWG-05 · الكمرة الخلفية / المانيفولد",
 "DWG-06-hydraulic-circuit":"DWG-06 · الدائرة الهيدروليكية",
 "DWG-07-operation":"DWG-07 · تسلسل التشغيل ومنطقة الخطر",
}
def datauri(name):
    raw=(root/"drawings"/f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64,"+base64.b64encode(raw).decode()

sheets = "\n".join(
 f'<figure class="sheet"><img src="{datauri(n)}" alt="{H.escape(c)}" loading="lazy">'
 f'<figcaption>{H.escape(c)}</figcaption></figure>' for n,c in caps.items())

# replace the drawings table section body with the sheets gallery
htmlbody = re.sub(r'<h2[^>]*>4\. الرسومات</h2>.*?(?=<hr\s*/?>)',
                  '<h2 id="s4">4. الرسومات</h2>\n<div class="sheets">'+sheets+'</div>\n'
                  '<p class="note">ملفات SVG الأصلية موجودة في المستودع تحت <code dir="ltr">docs/jack/drawings/</code> وتُفتح في أي برنامج CAD.</p>\n',
                  htmlbody, flags=re.S)

# ids + TOC from h2
toc=[]
def h2id(m):
    txt=re.sub("<[^>]+>","",m.group(1))
    num=txt.split(".")[0].strip()
    i=f"s{num}"
    toc.append((num, txt.split(".",1)[1].strip() if "." in txt else txt, i))
    return f'<h2 id="{i}"><span class="secno">{H.escape(num)}</span>{H.escape(txt.split(".",1)[1].strip() if "." in txt else txt)}</h2>'
htmlbody=re.sub(r'<h2[^>]*>(.*?)</h2>', h2id, htmlbody, flags=re.S)

toclinks="\n".join(f'<a href="#{i}"><span class="tn">{H.escape(n)}</span>{H.escape(t)}</a>' for n,t,i in toc)

# mark warning blockquotes / tables
htmlbody = htmlbody.replace("<table>",'<div class="tw"><table>').replace("</table>","</table></div>")
htmlbody = htmlbody.replace("<h1>","<h3 class=\"warnhead\">").replace("</h1>","</h3>")

tpl = (HERE / "shell.html").read_text(encoding="utf-8")
out = tpl.replace("<!--TOC-->", toclinks).replace("<!--BODY-->", htmlbody)
(HERE / "pt-jack-250.html").write_text(out, encoding="utf-8")
print("sections:", len(toc), "bytes:", len(out))
