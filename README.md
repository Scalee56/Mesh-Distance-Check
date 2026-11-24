# Mesh Distance Check

Add-on per Blender 4.2 o versioni successive. Mostra nella Vista 3D le distanze tra superfici mesh. Le misure delle superfici tengono conto delle trasformazioni degli oggetti e dei modificatori valutati.

## Installazione

1. [Scarica mesh_distance_check.zip](https://github.com/Scalee56/Mesh-Distance-Check/raw/refs/heads/main/mesh_distance_check.zip).
2. In Blender apri **Modifica → Preferenze → Add-on**, scegli **Installa da disco** dal menu e seleziona lo ZIP.
3. Attiva **Mesh Distance Check**. Nella Vista 3D premi **N** e apri la scheda **Mesh Distance**. Per vedere le misure, tieni attive le sovrapposizioni della viewport.

Se un aggiornamento precedente ha restituito `cannot import name 'closest_surfaces'`, installa lo ZIP aggiornato. Se Blender ha ancora la vecchia sessione aperta, chiudilo e riaprilo prima di attivare l’add-on.

## Distanza minima e heatmap

1. In modalità Oggetto seleziona due mesh con facce. Seleziona per ultima la mesh da colorare, così diventa quella attiva.
2. Premi **Misura distanza minima** per mostrare in giallo il segmento più corto tra le due superfici, con la misura nelle unità della scena. A distanza zero gli estremi coincidono e appare un punto.
3. Premi **Mostra heatmap** per colorare la mesh attiva. La palette a sei colori di Mesh Thickness Analyzer parte dal rosso per le distanze minori e arriva al blu per quelle maggiori. La scala verticale mostra minimo, punto medio e massimo. Le distanze vengono campionate ai vertici della superficie e i colori vengono interpolati sulle facce. Una mesh con pochi vertici produce una heatmap più approssimata.

## Sonda

Entra in modalità Modifica sulla mesh sorgente e seleziona un vertice in modalità di selezione vertici. Nel pannello **Mesh Distance**, scegli una **Destinazione** o lascia il campo vuoto per cercare fra le altre mesh visibili. Premi **Misura dal vertice selezionato**. La linea verde mostra il percorso dal vertice della mesh in modifica al punto più vicino sulla superficie di destinazione.

Le sovrapposizioni mostrano il risultato dell'ultima misurazione. Ricalcolale dopo aver spostato o modificato una mesh. Usa **Cancella risultati** per rimuoverle. Una mesh completamente contenuta in un'altra può avere una distanza positiva se le superfici sono separate.

## Prova rapida

Crea due cubi standard larghi 2 unità con i centri a X=0 e X=3. Il minimo atteso è 1 unità Blender. Per provare la sonda, seleziona un vertice del primo cubo sulla faccia rivolta verso il secondo: anche la sonda deve indicare 1 unità. Sposta il secondo centro a X=1 e ricalcola il minimo per ottenere 0.
