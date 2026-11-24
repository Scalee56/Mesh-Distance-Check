# Mesh Distance Check

Add-on per Blender 4.2 o versioni successive. Misura la distanza minima tra le superfici di due oggetti mesh, applicando le trasformazioni globali e usando la geometria risultante dai modificatori.

## Installazione

[Scarica mesh_distance_check.zip](https://github.com/Scalee56/Mesh-Distance-Check/raw/refs/heads/main/mesh_distance_check.zip).

1. Apri **Modifica → Preferenze → Add-on**.
2. Dal menu nell'angolo in alto a destra scegli **Installa da disco** e seleziona `mesh_distance_check.zip`.
3. Attiva **Mesh Distance Check**.

## Uso

1. Seleziona due oggetti mesh in modalità Oggetto.
2. Nella Vista 3D premi **N** e apri la scheda **Mesh Distance**.
3. Premi **Misura distanza minima** per vedere il risultato nelle unità della scena.

Le superfici a contatto o che si intersecano hanno distanza zero, entro la precisione numerica di Blender. Se una mesh chiusa è interamente contenuta in un'altra con uno spazio tra le superfici, il risultato è la distanza positiva tra le due superfici. Entrambe le mesh devono avere facce.

## Prova rapida

Con due cubi standard larghi 2 unità e i centri a X=0 e X=3, la distanza attesa è 1 unità Blender. Sposta il secondo centro a X=1 per ottenere 0.
