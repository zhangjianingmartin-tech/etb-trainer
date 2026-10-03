# Escape the Backrooms Trainer

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Русский](README.ru.md) | **Português**

Um overlay de informações com funções divertidas para *Escape the Backrooms* (Steam 1943950, UE 4.27). Escrito em Python puro, apenas com a biblioteca padrão. Lê e escreve a memória do jogo por fora e instala um pequeno hook em `UObject::ProcessEvent` para chamar as UFunctions do próprio jogo na thread do jogo.

> Apenas para o modo solo ou para a sua própria sala (com amigos que saibam), para diversão e para aprender engenharia reversa de UE.
> Este projeto não tem nenhuma relação com a Fancy Games nem com a Steam. Use por sua conta e risco; offsets e assinaturas podem parar de funcionar após atualizações do jogo.
>
> Observação: o painel na tela e as mensagens estão, por enquanto, apenas em chinês simplificado.

## Funções

**Overlay** (somente leitura, não altera o jogo)
- Mostra na tela monstros, itens, saídas, zonas de queda e colegas com a distância; alvos fora da tela recebem uma seta na borda
- Painel no canto superior esquerdo: nível, coordenadas, estamina, distância até o monstro mais próximo (vermelho a menos de 15 m), lista de saídas e itens
- Some quando o jogo não está em primeiro plano e fecha quando o jogo fecha

**Atalhos** (seu papel é detectado automaticamente: solo / anfitrião / cliente)

| Tecla | Anfitrião / solo | Cliente |
|---|---|---|
| F5 | Possuir o monstro mais próximo (WASD para andar, mouse para girar, Espaço para pular, Shift para correr); aperte de novo para voltar ao seu corpo | Mudar para a visão do monstro mais próximo (só assistir) |
| F6 | Congelar / descongelar todos os monstros | Indisponível |
| F7 | Voar + atravessar paredes (Espaço sobe, Ctrl desce) | Indisponível |
| F2 | Aumento de velocidade + estamina infinita | Aumento de velocidade (via RPC de servidor) |
| F3 | Visão em terceira pessoa | Igual |
| F4 / Shift+F4 | Trocar visual: fantasias do jogo (visíveis para os outros) ou modelos de monstros/personagens do nível (visíveis só para você) | Igual |
| Insert | Teleportar para a saída mais próxima | Indisponível |
| Delete | Reviver no local onde você morreu | Envia um pedido de renascimento ao anfitrião (geralmente ignorado) |
| PgUp / PgDn + Home | Escolher um item e gerá-lo nas suas mãos | Igual |
| F8 / F9 / F10 | Ocultar overlay / alternar marcadores de itens / alternar marcadores de objetos interativos | Igual |
| End | Reverter todas as alterações, remover o hook e sair | Igual |

## Como usar

1. Coloque o jogo em modo **janela** ou **janela sem bordas** (tela cheia exclusiva cobre o overlay) e entre em um nível.
2. Escolha:
   - baixe `ETB-Trainer.exe` em Releases e dê dois cliques (não precisa de Python), ou
   - instale o Python 3.10+, baixe o código-fonte e dê dois cliques em `启动覆盖层.bat` ("iniciar overlay"), ou execute `python etb_overlay.py`.
3. Aperte **End** para sair. Primeiro são revertidos possessão, congelamento, voo, visuais etc., depois o hook é removido.

O exe de arquivo único é empacotado com PyInstaller e pode ser apontado por antivírus como falso positivo. Se isso incomodar, execute pelo código-fonte.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `etb_overlay.py` | Ponto de entrada: janela do overlay, leitura de memória, classificação de atores, projeção do mundo para a tela |
| `etb_trainer.py` | Funções dos atalhos, executadas em uma thread em segundo plano do processo do overlay |
| `etb_call.py` | Hook de ProcessEvent + chamador de UFunctions que monta os parâmetros por reflexão (suporta chamadas em lote) |
| `etb_ue.lua` | Script do Cheat Engine: localiza GNames / GObjects / GWorld por AOB, com funções auxiliares para nomes, reflexão e percurso de atores |
| `NOTES.md` | Notas de engenharia reversa (em chinês): globais, cadeias de ponteiros, offsets, funcionamento do hook |
| `FUNCTIONS.md` | Lista de funções chamáveis (descrições em chinês; seleção + assinaturas completas de 1729 funções em 212 classes do jogo) |

## Como funciona

- Ao iniciar, as seções executáveis do módulo principal são varridas com assinaturas AOB para encontrar `GNames` (FNamePool), `GUObjectArray` e `GWorld`. Todo o resto é lido conforme a estrutura do UE 4.27 e a reflexão em tempo de execução.
- Os primeiros 19 bytes de `ProcessEvent` são trocados por um `jmp` para uma code cave. Ela verifica se a thread atual é a thread do jogo, reserva a flag de chamada com `lock cmpxchg`, executa o lote de chamadas escrito de fora, depois executa o prólogo original e volta. Assim, todas as chamadas de funções do jogo acontecem na própria thread principal do jogo.
- Detecção do papel: se `Actor::Role` do personagem local for Authority, `World::NetDriver` diferencia solo de anfitrião; AutonomousProxy significa cliente.

Detalhes em [NOTES.md](NOTES.md) (em chinês).

## Compatibilidade

Escrito e testado no build da Steam 24997718. Se, após uma atualização, aparecer "AOB 没找到" (AOB não encontrado) ou "ProcessEvent 开头字节和预期不同" (prólogo de ProcessEvent inesperado), é preciso localizar os endereços de novo.

## Licença

[MIT](LICENSE)
