"""
Verifica se a tabela foi provisionada corretamente pelo Terraform.
A criação da tabela e Global Table é responsabilidade do Terraform (../terraform/).

Uso:
  cd ../terraform && terraform init && terraform apply
  cd ../scripts  && python3 01_setup_table.py   # valida o resultado
"""
from dotenv import load_dotenv
from utils import REGIOES, status_tabela

load_dotenv()

TABELA = "Pedidos"


def verificar():
    print("Verificando infraestrutura provisionada pelo Terraform...\n")
    tudo_ok = True

    for regiao in REGIOES:
        info = status_tabela(regiao)
        ok = info["status"] == "ACTIVE"
        simbolo = "✓" if ok else "✗"
        print(f"  {simbolo} {regiao}: status={info['status']} | itens={info.get('itens', 'N/A')}")
        if not ok:
            tudo_ok = False

    if tudo_ok:
        print("\nTabela 'Pedidos' ativa nas 3 regiões.")
    else:
        print("\nAviso: alguma região não está ACTIVE — comportamento esperado durante testes de falha.")


if __name__ == "__main__":
    verificar()
