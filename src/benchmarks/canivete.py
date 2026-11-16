"""
Canivete.cc benchmark pages.

Representative crawled pages of Canivete.cc. One benchmark site among others:
its roles, clusters and thresholds live in config/sites/canivete.yaml, exactly like
any user's site config; nothing in the engines is specific to it.
"""

from typing import List

from src.connectors.sitemap_crawler import ParsedPage


def build_canivete_pages() -> List[ParsedPage]:
    return [
        # --- CLUSTER 1: TRABALHISTA & RH (Pillar & Tools) ---
        ParsedPage(
            url="https://canivete.cc/guias/guia-rescisao-trabalhista-clt-2026/",
            title="Guia Completo da Rescisão Trabalhista CLT 2026",
            h1="Guia Completo da Rescisão Trabalhista CLT 2026: Cálculos, Prazos e Direitos",
            paragraphs=[
                "A rescisão do contrato de trabalho sob as regras da Consolidação das Leis do Trabalho (CLT) é um dos momentos mais importantes na relação entre empregado e empregador.",
                "Iniciativa da empresa. O trabalhador recebe saldo de salário, aviso prévio, 13º proporcional, férias vencidas/proporcionais + 1/3, saque do FGTS com multa rescisória de 40% e seguro-desemprego.",
                "Pela Lei Federal nº 12.506/2011, todo trabalhador demitido sem justa causa tem direito a um aviso prévio de no mínimo 30 dias, acrescido de 3 dias adicionais para cada ano completo de serviço.",
                "Com a Reforma Trabalhista, o trabalhador que pede demissão precisa formalizar seu pedido com uma carta de demissão expressa para evitar desconto do aviso prévio.",
                "Após o cálculo da rescisão, caso o trabalhador tenha direito ao benefício do seguro-desemprego, ele deve solicitar as guias para dar entrada nas parcelas.",
            ],
            existing_internal_links=["https://canivete.cc/financas/calculadora-rescisao-clt/"],
        ),
        ParsedPage(
            url="https://canivete.cc/financas/calculadora-rescisao-clt/",
            title="Calculadora de Rescisão de Contrato CLT 2026",
            h1="Calculadora de Rescisão Trabalhista CLT",
            paragraphs=[
                "Calcule sua rescisão trabalhista com aviso prévio proporcional, 13º salário, férias proporcionais, saldo de salário e multa de 40% do FGTS.",
                "Se você foi demitido sem justa causa e possui tempo mínimo de carteira assinada, calcule também o valor e quantidade das parcelas do seu seguro-desemprego.",
                "Caso você esteja pedindo demissão e precise redigir o documento formal para entregar ao RH, utilize nosso modelo de carta de demissão.",
                "Entenda todas as regras e o passo a passo legal consultando o guia completo de rescisão trabalhista da CLT.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://canivete.cc/financas/calculadora-seguro-desemprego/",
            title="Calculadora de Seguro-Desemprego 2026",
            h1="Simulador de Seguro-Desemprego: Parcelas e Valores",
            paragraphs=[
                "Descubra a quantidade de parcelas (de 3 a 5) e o valor exato do seguro-desemprego com base na média dos seus últimos três salários brutos.",
                "O benefício é garantido ao trabalhador dispensado sem justa causa que comprove vínculo empregatício e não possua outra fonte de renda.",
                "Para conferir o total de todas as verbas rescisórias antes de solicitar o benefício, acesse a calculadora de rescisão CLT.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://canivete.cc/negocios/gerador-carta-demissao/",
            title="Gerador de Carta de Demissão Online",
            h1="Gerador de Carta de Demissão com ou sem Aviso Prévio",
            paragraphs=[
                "Gere instantaneamente sua carta de demissão formal, escolhendo entre cumprimento do aviso prévio trabalhado ou solicitação de dispensa.",
                "Ao pedir demissão, o trabalhador abre mão do saque do FGTS e da multa de 40%, recebendo apenas saldo de salário e férias/13º proporcionais.",
                "Antes de entregar o documento, veja quanto você irá receber na simulação completa da rescisão contratual.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://canivete.cc/guias/calculo-salario-liquido-inss-irpf-2026/",
            title="Como Calcular o Salário Líquido 2026: Tabela INSS e IRPF",
            h1="Guia Passo a Passo: Cálculo do Salário Líquido em 2026",
            paragraphs=[
                "O cálculo do salário líquido envolve a aplicação da tabela progressiva fatiada do INSS e a dedução da alíquota efetiva do Imposto de Renda Retido na Fonte (IRPF).",
                "Para quem recebe adicionais como horas extras ou adicional noturno, essas verbas integram a base de cálculo para a incidência de encargos.",
                "Se você está avaliando uma proposta de trabalho PJ versus contratação com carteira assinada, compare a equivalência salarial real entre os regimes.",
            ],
            existing_internal_links=["https://canivete.cc/financas/calculadora-salario-liquido/"],
        ),
        ParsedPage(
            url="https://canivete.cc/financas/calculadora-salario-liquido/",
            title="Calculadora de Salário Líquido 2026 Oficial",
            h1="Calculadora de Salário Líquido 2026",
            paragraphs=[
                "Descubra quanto sobra no seu bolso com desconto oficial progressivo do INSS, IRPF 2026, dependentes, pensão alimentícia e vale-transporte.",
                "Se você realiza jornadas extraordinárias com frequência, faça o cálculo de horas extras para incluir o valor total no seu holerite.",
                "Dúvidas sobre como funciona a tabela fatiada do INSS? Leia o guia completo de cálculo do salário líquido.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://canivete.cc/guias/clt-vs-pj-equivalencia-salarial/",
            title="CLT vs PJ: Qual Vale Mais a Pena em 2026?",
            h1="Comparativo CLT vs PJ: Como Calcular a Equivalência",
            paragraphs=[
                "Migrar de CLT para PJ exige calcular benefícios perdidos como 13º salário, férias remuneradas com 1/3, FGTS de 8% e seguro-desemprego.",
                "Para prestadores de serviços PJ, é indispensável firmar um contrato de prestação de serviços detalhado para evitar descaracterização e garantir segurança jurídica.",
                "Use nosso comparador CLT vs PJ para simular a remuneração bruta necessária como PJ para igualar seu padrão atual CLT.",
            ],
            existing_internal_links=["https://canivete.cc/financas/comparador-clt-vs-pj/"],
        ),
        ParsedPage(
            url="https://canivete.cc/negocios/gerador-contrato-prestacao-servicos/",
            title="Gerador de Contrato de Prestação de Serviços",
            h1="Contrato de Prestação de Serviços com Validade Jurídica",
            paragraphs=[
                "Crie uma minuta contratual robusta para freelancers, profissionais liberais e empresas PJ de acordo com o Código Civil brasileiro.",
                "Para formalizar a quitação dos valores acordados nas entregas de serviços, emita também um recibo de pagamento profissional.",
                "Proteja os dados pessoais de clientes e usuários inserindo cláusulas de conformidade com a LGPD e termos de uso.",
            ],
            existing_internal_links=[],
        ),
        # --- CLUSTER 2: CRÉDITO & PREVIDÊNCIA (Money Pages) ---
        ParsedPage(
            url="https://canivete.cc/financas/simulador-emprestimo-consignado-inss/",
            title="Simulador de Empréstimo Consignado INSS 2026",
            h1="Simulador de Empréstimo Consignado INSS: Margem e Parcelas",
            paragraphs=[
                "Simule o valor liberado no empréstimo consignado para aposentados e pensionistas do INSS com a taxa máxima de juros de 1,66% ao mês e prazo de até 84 meses.",
                "A margem consignável legal permite comprometer até 35% do benefício líquido mensal da aposentadoria.",
                "Se você ainda não se aposentou, faça o diagnóstico completo com a calculadora de aposentadoria INSS 2026 para planejar suas regras de transição.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://canivete.cc/financas/calculadora-aposentadoria-inss/",
            title="Calculadora de Aposentadoria INSS 2026",
            h1="Calculadora de Aposentadoria INSS 2026: Regras de Transição",
            paragraphs=[
                "Descubra quando você poderá se aposentar após a Reforma da Previdência: Regra dos Pontos 2026, Idade Mínima, Pedágio 50% e 100%.",
                "Ao planejar seu benefício futuro, saiba quanto poderá comprometer em crédito na simulação de consignado INSS.",
            ],
            existing_internal_links=[],
        ),
        # --- CLUSTER 3: DEV & TECH ---
        ParsedPage(
            url="https://canivete.cc/guias/qr-code-pix-emv-br-code-como-funciona/",
            title="Como Funciona o QR Code Pix: Especificações EMV e BR Code",
            h1="Guia Técnico: Estrutura do Payload do QR Code Pix",
            paragraphs=[
                "O QR Code Pix segue os padrões internacionais EMVCo e as especificações do Banco Central do Brasil para geração de cobranças estáticas e dinâmicas.",
                "Você pode gerar cobranças personalizadas com chave Pix, valor exato e identificador de transação instantaneamente no gerador de QR Code Pix.",
                "Para desenvolvedores integrando APIs de pagamento, valide documentos de clientes usando o validador de CPF e CNPJ.",
            ],
            existing_internal_links=["https://canivete.cc/desenvolvedores/gerador-qr-code-pix/"],
        ),
        ParsedPage(
            url="https://canivete.cc/desenvolvedores/gerador-qr-code-pix/",
            title="Gerador de QR Code Pix Oficial Online",
            h1="Gerador de QR Code Pix Estático e Copia e Cola",
            paragraphs=[
                "Crie seu código Pix 'Copia e Cola' e imagem QR Code oficial com chave aleatória, CPF, CNPJ, e-mail ou telefone para receber pagamentos.",
                "Para emitir notas e cadastrar pagadores sem erros na sua plataforma, utilize o validador de CPF/CNPJ.",
                "Consulte os detalhes técnicos da composição dos campos EMV no guia de especificações do QR Code Pix.",
            ],
            existing_internal_links=[],
        ),
    ]
