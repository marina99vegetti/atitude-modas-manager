from flask import Flask, request, redirect, url_for, render_template, flash
import sqlite3, os
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "Configure a variável de ambiente SECRET_KEY antes de iniciar o sistema."
    )
DB_PATH = os.environ.get("DATABASE_PATH", str(Path(__file__).with_name("atitude_web.db")))

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def setup():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS produtos (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
          categoria TEXT DEFAULT '', quantidade INTEGER NOT NULL DEFAULT 0,
          custo REAL NOT NULL DEFAULT 0, preco REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS clientes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, telefone TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS fornecedores (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
          telefone TEXT DEFAULT '', observacao TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS vendas (
          id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL,
          cliente_nome TEXT DEFAULT 'Consumidor', total REAL NOT NULL DEFAULT 0,
          pagamento TEXT DEFAULT 'Dinheiro');
        CREATE TABLE IF NOT EXISTS itens_venda (
          id INTEGER PRIMARY KEY AUTOINCREMENT, venda_id INTEGER NOT NULL,
          produto_id INTEGER, produto_nome TEXT NOT NULL, quantidade INTEGER NOT NULL,
          preco REAL NOT NULL, FOREIGN KEY(venda_id) REFERENCES vendas(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS contas_receber (
          id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_nome TEXT NOT NULL,
          descricao TEXT DEFAULT '', valor REAL NOT NULL DEFAULT 0,
          pago REAL NOT NULL DEFAULT 0, data TEXT NOT NULL);
        """)
setup()

def brl(v):
    return ("R$ {:,.2f}".format(float(v or 0))).replace(",", "X").replace(".", ",").replace("X", ".")

@app.context_processor
def helpers():
    return {"brl": brl, "ano": datetime.now().year}

@app.route("/")
def home():
    with db() as con:
        produtos = con.execute("SELECT COUNT(*) n FROM produtos").fetchone()["n"]
        unidades = con.execute("SELECT COALESCE(SUM(quantidade),0) n FROM produtos").fetchone()["n"]
        vendas = con.execute("SELECT COALESCE(SUM(total),0) n FROM vendas WHERE date(data)=date('now','localtime')").fetchone()["n"]
        pendente = con.execute("SELECT COALESCE(SUM(valor-pago),0) n FROM contas_receber").fetchone()["n"]
        recentes = con.execute("SELECT * FROM vendas ORDER BY id DESC LIMIT 5").fetchall()
        baixos = con.execute("SELECT * FROM produtos WHERE quantidade <= 3 ORDER BY quantidade,nome LIMIT 5").fetchall()
    return render_template("home.html", produtos=produtos, unidades=unidades, vendas=vendas, pendente=pendente, recentes=recentes, baixos=baixos, titulo="Visão geral")

@app.route("/produtos", methods=["GET","POST"])
def produtos():
    if request.method == "POST":
        nome=request.form.get("nome","").strip()
        if not nome:
            flash("Informe o nome do produto.", "erro")
        else:
            try:
                quantidade=int(request.form.get("quantidade","0"))
                custo=float(request.form.get("custo","0").replace(",","."))
                preco=float(request.form.get("preco","0").replace(",","."))
                if min(quantidade,custo,preco)<0: raise ValueError()
                with db() as con:
                    con.execute("INSERT INTO produtos(nome,categoria,quantidade,custo,preco) VALUES(?,?,?,?,?)",(nome,request.form.get("categoria","").strip(),quantidade,custo,preco))
                flash("Produto cadastrado.", "ok")
            except (ValueError, sqlite3.Error):
                flash("Confira quantidade, custo e preço.", "erro")
        return redirect(url_for("produtos"))
    q=request.args.get("q","").strip()
    with db() as con:
        rows=con.execute("SELECT * FROM produtos WHERE nome LIKE ? OR categoria LIKE ? ORDER BY nome", (f"%{q}%",f"%{q}%")).fetchall()
    return render_template("produtos.html", produtos=rows, q=q, titulo="Produtos e estoque")

@app.post("/produtos/<int:id>/excluir")
def excluir_produto(id):
    with db() as con: con.execute("DELETE FROM produtos WHERE id=?",(id,))
    flash("Produto removido.", "ok")
    return redirect(url_for("produtos"))

@app.route("/clientes", methods=["GET","POST"])
def clientes():
    if request.method=="POST":
        nome=request.form.get("nome","").strip()
        if nome:
            with db() as con: con.execute("INSERT INTO clientes(nome,telefone) VALUES(?,?)",(nome,request.form.get("telefone","").strip()))
            flash("Cliente cadastrado.", "ok")
        else: flash("Informe o nome do cliente.", "erro")
        return redirect(url_for("clientes"))
    with db() as con: rows=con.execute("SELECT * FROM clientes ORDER BY nome").fetchall()
    return render_template("cadastros.html", rows=rows, tipo="Clientes", endpoint="clientes", campos=[("nome","Nome do cliente"),("telefone","Telefone")], titulo="Clientes")

@app.route("/fornecedores", methods=["GET","POST"])
def fornecedores():
    if request.method=="POST":
        nome=request.form.get("nome","").strip()
        if nome:
            with db() as con: con.execute("INSERT INTO fornecedores(nome,telefone,observacao) VALUES(?,?,?)",(nome,request.form.get("telefone","").strip(),request.form.get("observacao","").strip()))
            flash("Fornecedor cadastrado.", "ok")
        else: flash("Informe o nome do fornecedor.", "erro")
        return redirect(url_for("fornecedores"))
    with db() as con: rows=con.execute("SELECT * FROM fornecedores ORDER BY nome").fetchall()
    return render_template("cadastros.html", rows=rows, tipo="Fornecedores", endpoint="fornecedores", campos=[("nome","Nome do fornecedor"),("telefone","Telefone"),("observacao","Observação")], titulo="Fornecedores")

@app.route("/vendas", methods=["GET","POST"])
def vendas():
    if request.method=="POST":
        try:
            produto_id=int(request.form["produto_id"]); quantidade=int(request.form["quantidade"])
            with db() as con:
                p=con.execute("SELECT * FROM produtos WHERE id=?",(produto_id,)).fetchone()
                if not p: raise ValueError("Selecione um produto válido.")
                if quantidade<1 or quantidade>p["quantidade"]: raise ValueError("Quantidade indisponível no estoque.")
                cliente=request.form.get("cliente","").strip() or "Consumidor"
                total=quantidade*p["preco"]
                cur=con.execute("INSERT INTO vendas(data,cliente_nome,total,pagamento) VALUES(?,?,?,?)",(datetime.now().strftime("%Y-%m-%d %H:%M:%S"),cliente,total,request.form.get("pagamento","Dinheiro")))
                con.execute("INSERT INTO itens_venda(venda_id,produto_id,produto_nome,quantidade,preco) VALUES(?,?,?,?,?)",(cur.lastrowid,p["id"],p["nome"],quantidade,p["preco"]))
                con.execute("UPDATE produtos SET quantidade=quantidade-? WHERE id=?",(quantidade,produto_id))
            flash("Venda registrada e estoque atualizado.", "ok")
        except (ValueError, KeyError, sqlite3.Error) as e:
            flash(str(e) or "Não foi possível registrar a venda.", "erro")
        return redirect(url_for("vendas"))
    with db() as con:
        ps=con.execute("SELECT * FROM produtos WHERE quantidade>0 ORDER BY nome").fetchall()
        rows=con.execute("SELECT * FROM vendas ORDER BY id DESC LIMIT 100").fetchall()
    return render_template("vendas.html", produtos=ps, vendas=rows, titulo="Vendas")

@app.route("/credito", methods=["GET","POST"])
def credito():
    if request.method=="POST":
        try:
            valor=float(request.form.get("valor","0").replace(",","."))
            if valor<=0: raise ValueError()
            with db() as con: con.execute("INSERT INTO contas_receber(cliente_nome,descricao,valor,pago,data) VALUES(?,?,?,?,?)",(request.form.get("cliente","").strip() or "Cliente",request.form.get("descricao","").strip(),valor,0,datetime.now().strftime("%Y-%m-%d")))
            flash("Conta de crédito registrada.", "ok")
        except (ValueError, sqlite3.Error): flash("Informe um valor válido maior que zero.", "erro")
        return redirect(url_for("credito"))
    with db() as con: rows=con.execute("SELECT *, valor-pago AS saldo FROM contas_receber ORDER BY id DESC").fetchall()
    return render_template("credito.html", rows=rows, titulo="Gestão de crédito")

@app.post("/credito/<int:id>/pagar")
def pagar(id):
    try:
        valor=float(request.form.get("valor","0").replace(",","."))
        with db() as con:
            conta=con.execute("SELECT * FROM contas_receber WHERE id=?",(id,)).fetchone()
            if not conta: raise ValueError()
            saldo=conta["valor"]-conta["pago"]
            if valor<=0 or valor>saldo: raise ValueError()
            con.execute("UPDATE contas_receber SET pago=pago+? WHERE id=?",(valor,id))
        flash("Pagamento parcial/total registrado.", "ok")
    except (ValueError, sqlite3.Error): flash("Valor de pagamento inválido.", "erro")
    return redirect(url_for("credito"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
